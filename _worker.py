"""Изолированный запуск проверенного checksum ядра validation."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import pickle
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 256
EXECUTION_TIMEOUT_SECONDS = 6 * 60 * 60
CHECKSUM_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


def _decode_payload(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, (bytearray, memoryview)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        try:
            raw = base64.b64decode(payload, validate=True)
        except ValueError as error:
            raise ValueError("received_codebase содержит некорректный base64") from error
    elif hasattr(payload, "columns") and "archive_b64" in payload.columns:
        if len(payload) != 1:
            raise ValueError(
                "received_codebase dataframe должен содержать одну строку"
            )
        raw = _decode_payload(payload["archive_b64"].iloc[0])
    else:
        raise TypeError(
            "received_codebase должен быть bytes, base64-строкой или dataframe "
            "с единственной колонкой archive_b64"
        )
    if not raw:
        raise ValueError("received_codebase пуст")
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"received_codebase превышает лимит {MAX_ARCHIVE_BYTES} байт"
        )
    return raw


def _verify(raw: bytes, checksum: Any) -> str:
    expected = str(checksum or "").strip().lower()
    if CHECKSUM_PATTERN.fullmatch(expected) is None:
        raise ValueError("received_checksum должен быть SHA-256 в hex")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(
            "sha256 received_codebase не совпал с received_checksum: "
            f"ожидался {expected}, рассчитан {actual}"
        )
    return actual


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    if not members:
        raise ValueError("архив validation пуст")
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"в архиве validation больше {MAX_MEMBERS} объектов")
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not member.name:
            raise ValueError(f"небезопасный путь в архиве validation: {member.name!r}")
        if not member.isfile():
            raise ValueError(
                f"архив validation должен содержать только файлы: {member.name!r}"
            )
        total += member.size
    if total > MAX_EXTRACTED_BYTES:
        raise ValueError(
            f"распакованная кодовая база превышает {MAX_EXTRACTED_BYTES} байт"
        )


def _extract(raw: bytes, target: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        _validate_members(members)
        archive.extractall(path=target, members=members, filter="data")
    entrypoint = target / "validation.py"
    if not entrypoint.is_file():
        raise FileNotFoundError("в received_codebase отсутствует validation.py")
    return entrypoint


def _execute(entrypoint: Path, params: Mapping[str, Any]) -> Any:
    project_dir = entrypoint.parent
    params_path = project_dir / ".params.pkl"
    result_path = project_dir / ".result.pkl"
    params_path.write_bytes(pickle.dumps(dict(params), protocol=pickle.HIGHEST_PROTOCOL))
    bootstrap = (
        "import pickle, runpy, sys; "
        "script, params_file, result_file = sys.argv[1:4]; "
        "sys.argv = [script]; "
        "namespace = runpy.run_path(script); "
        "params = pickle.load(open(params_file, 'rb')); "
        "result = namespace['main'](**params); "
        "pickle.dump(result, open(result_file, 'wb'), protocol=pickle.HIGHEST_PROTOCOL)"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_dir)
    try:
        completed = subprocess.run(
            (
                sys.executable,
                "-u",
                "-c",
                bootstrap,
                str(entrypoint),
                str(params_path),
                str(result_path),
            ),
            cwd=project_dir,
            env=env,
            stderr=subprocess.PIPE,
            text=True,
            timeout=EXECUTION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"validation не завершилась за {EXECUTION_TIMEOUT_SECONDS} секунд"
        ) from error
    if completed.returncode != 0:
        details = (completed.stderr or "").strip()[-4000:]
        suffix = f": {details}" if details else ""
        raise RuntimeError(
            f"validation завершилась с кодом {completed.returncode}{suffix}"
        )
    if not result_path.is_file():
        raise RuntimeError("validation не создала файл результата")
    return pickle.loads(result_path.read_bytes())


def _validate_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError("validation.main должна вернуть dict")
    missing = {"report_html", "status", "verdict"} - set(result)
    if missing:
        raise ValueError(
            "результат validation.main не содержит обязательные поля: "
            + ", ".join(sorted(missing))
        )
    if not isinstance(result["report_html"], str) or not result["report_html"].strip():
        raise TypeError("report_html должен быть непустой строкой")
    status = result["status"]
    if not isinstance(status, dict) or status.get("value") not in {
        "green",
        "amber",
        "red",
    }:
        raise ValueError("status.value должен быть green, amber или red")
    if not isinstance(status.get("title"), str) or not status["title"].strip():
        raise TypeError("status.title должен быть непустой строкой")
    if not isinstance(result["verdict"], dict):
        raise TypeError("verdict должен быть dict")
    return result


def run_validation(
    payload: Any, checksum: Any, params: Mapping[str, Any]
) -> dict[str, Any]:
    raw = _decode_payload(payload)
    _verify(raw, checksum)
    scratch_root = Path(tempfile.gettempdir()) / "laim-ars-validation"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="project_", dir=scratch_root) as temporary:
        entrypoint = _extract(raw, Path(temporary))
        return _validate_result(_execute(entrypoint, params))
