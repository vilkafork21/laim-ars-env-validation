"""SberDS-нода проверки качества телеметрии с выбором итога K1–K6 / K1–K7."""

from __future__ import annotations

from typing import Any

from _worker import run_validation


def main(
    received_codebase: Any,
    received_checksum: str,
    spans_df: Any = None,
    source_path: str = "",
    device: str = "cpu",
    significance: str = "C",
    verdict_scope: str = "quality",
    recast: bool = True,
    collect_batch_size: str = "4",
    window_days: str = "30",
    max_nulls: str = "",
    max_rules: str = "",
    max_dups: str = "",
    max_breaks: str = "",
    volume_target: str = "",
    volume_steepness: str = "",
    rate_target: str = "",
    min_eff_traces: str = "",
    max_loss: str = "",
    min_quality: str = "",
    ready_at: str = "",
    pilot_at: str = "",
) -> dict[str, Any]:
    """Исполняет ровно ту версию validation, checksum которой получен с порта.

    Отличие от laim-ars-env-validation-uf — параметр verdict_scope: по умолчанию
    светофор status считается только по качеству данных K1–K6, готовность K7
    рассчитывается и показывается в отчёте, но итог не окрашивает.
    """
    params = {
        "spans_df": spans_df,
        "source_path": source_path,
        "device": device,
        "significance": significance,
        "verdict_scope": verdict_scope,
        "recast": recast,
        "collect_batch_size": collect_batch_size,
        "window_days": window_days,
        "max_nulls": max_nulls,
        "max_rules": max_rules,
        "max_dups": max_dups,
        "max_breaks": max_breaks,
        "volume_target": volume_target,
        "volume_steepness": volume_steepness,
        "rate_target": rate_target,
        "min_eff_traces": min_eff_traces,
        "max_loss": max_loss,
        "min_quality": min_quality,
        "ready_at": ready_at,
        "pilot_at": pilot_at,
        "dont_colorize_log": True,
    }
    return run_validation(received_codebase, received_checksum, params)
