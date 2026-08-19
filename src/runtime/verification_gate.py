"""Fail-closed stage gates for agent execution evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final


VERIFICATION_GATE_SCHEMA_VERSION: Final = "verification_gate/v1"
GATE_STAGES: Final = ("handoff", "execution", "tests", "review")
_REQUIREMENTS: Final[dict[str, tuple[str, ...]]] = {
    "handoff": ("handoff_envelope_valid",),
    "execution": ("handoff_envelope_valid", "runtime_observed", "correlation_id"),
    "tests": ("handoff_envelope_valid", "runtime_observed", "correlation_id", "test_status", "test_evidence_ref"),
    "review": ("handoff_envelope_valid", "runtime_observed", "correlation_id", "test_status", "test_evidence_ref", "review_status", "review_evidence_ref"),
}


def evaluate_verification_gate(stage: str, evidence: Mapping[str, object] | None = None) -> dict[str, object]:
    """Return a gate decision; missing evidence always blocks advancement."""
    if stage not in GATE_STAGES:
        raise ValueError(f"unsupported verification gate stage: {stage}")
    supplied = evidence if isinstance(evidence, Mapping) else {}
    missing = [key for key in _REQUIREMENTS[stage] if not _evidence_present(key, supplied)]
    passed = not missing
    next_stage = GATE_STAGES[GATE_STAGES.index(stage) + 1] if passed and stage != GATE_STAGES[-1] else None
    return {
        "schema_version": VERIFICATION_GATE_SCHEMA_VERSION,
        "stage": stage,
        "status": "passed" if passed else "blocked",
        "missing_evidence": missing,
        "next_stage": next_stage,
        "claim_boundary": "A passed gate proves only the declared evidence for this stage; it is not proof of later stages or production outcome.",
    }


def validate_verification_gate(gate: Mapping[str, object] | object) -> list[str]:
    if not isinstance(gate, Mapping):
        return ["gate must be an object"]
    errors: list[str] = []
    if gate.get("schema_version") != VERIFICATION_GATE_SCHEMA_VERSION:
        errors.append("schema_version is invalid")
    if gate.get("stage") not in GATE_STAGES:
        errors.append("stage is invalid")
    if gate.get("status") not in {"passed", "blocked"}:
        errors.append("status is invalid")
    missing = gate.get("missing_evidence")
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        errors.append("missing_evidence must be a list of strings")
    if gate.get("status") == "passed" and missing != []:
        errors.append("passed gate must have no missing evidence")
    if gate.get("status") == "blocked" and not missing:
        errors.append("blocked gate must name missing evidence")
    if "not" not in str(gate.get("claim_boundary", "")).casefold():
        errors.append("claim_boundary must state a limitation")
    return errors


def _evidence_present(key: str, evidence: Mapping[str, object]) -> bool:
    value = evidence.get(key)
    if key.endswith("_valid") or key == "runtime_observed":
        return value is True
    if key == "test_status":
        return value in {"passed", "success"}
    if key == "review_status":
        return value in {"passed", "approved"}
    return isinstance(value, str) and bool(value.strip())
