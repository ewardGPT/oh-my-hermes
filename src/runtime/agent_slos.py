"""Bounded SLO projections over normalized, metadata-only run records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final


AGENT_SLO_SCHEMA_VERSION: Final = "agent_slos/v1"


def project_agent_slos(records: Sequence[Mapping[str, object]], *, max_latency_ms: int = 60_000, max_cost_usd: float = 1.0) -> dict[str, object]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ValueError("SLO records must be a sequence")
    valid = [record for record in records if isinstance(record, Mapping)]
    metrics = {
        "success_rate": _ratio(valid, "outcome", "completed"),
        "recovery_rate": _ratio(valid, "recovery", "completed"),
        "evidence_completeness": _boolean_ratio(valid, "evidence_complete"),
        "latency_ms": _average(valid, "latency_ms"),
        "cost_usd": _average(valid, "cost_usd"),
        "escalation_rate": _ratio(valid, "escalated", True),
    }
    return {
        "schema_version": AGENT_SLO_SCHEMA_VERSION,
        "record_count": len(valid),
        "metrics": metrics,
        "thresholds": {"max_latency_ms": max_latency_ms, "max_cost_usd": max_cost_usd},
        "threshold_status": {
            "latency": _threshold(metrics["latency_ms"], max_latency_ms, lower=True),
            "cost": _threshold(metrics["cost_usd"], max_cost_usd, lower=True),
        },
        "claim_boundary": "SLOs are projections over supplied metadata records, not provider billing, user satisfaction, causal attribution, or proof about unrecorded runs.",
    }


def _ratio(records: list[Mapping[str, object]], key: str, expected: object) -> dict[str, object]:
    observed = [record[key] for record in records if key in record]
    if not observed:
        return {"state": "unknown", "value": None, "reason": "no_observed_records"}
    return {"state": "observed", "value": sum(value == expected for value in observed) / len(observed), "reason": ""}


def _boolean_ratio(records: list[Mapping[str, object]], key: str) -> dict[str, object]:
    return _ratio(records, key, True)


def _average(records: list[Mapping[str, object]], key: str) -> dict[str, object]:
    values = [value for record in records if isinstance((value := record.get(key)), (int, float)) and not isinstance(value, bool)]
    if not values:
        return {"state": "unknown", "value": None, "reason": "no_observed_metric"}
    numeric_values = [float(value) for value in values]
    return {"state": "observed", "value": sum(numeric_values) / len(numeric_values), "reason": ""}


def _threshold(metric: Mapping[str, object], limit: float, *, lower: bool) -> str:
    if metric.get("state") != "observed":
        return "unknown"
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    return "within" if (value <= limit if lower else value >= limit) else "breached"
