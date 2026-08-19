"""Versioned, resumable handoff state shared by wrapper surfaces.

This envelope describes work state and evidence; it does not grant authority.
Authority remains owned by ``action_gate`` and its task-authority envelope.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


HANDOFF_ENVELOPE_SCHEMA_VERSION = "handoff_envelope/v1"
HANDOFF_ENVELOPE_KEYS = (
    "schema_version",
    "objective",
    "state",
    "decisions",
    "assumptions",
    "evidence",
    "risks",
    "next_action",
    "stop_conditions",
    "claim_boundary",
)
HANDOFF_ENVELOPE_STATES = ("prepared", "in_progress", "blocked", "completed")


def _text(value: object, label: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")
        return ""
    return value


def _string_list(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} must be a list")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{label}[{index}] must be a non-empty string")


def validate_handoff_envelope(envelope: Any) -> list[str]:
    """Return contract errors without raising, preserving old callers."""
    errors: list[str] = []
    if not isinstance(envelope, dict):
        return ["handoff envelope must be an object"]
    extra = sorted(set(envelope) - set(HANDOFF_ENVELOPE_KEYS))
    missing = sorted(set(HANDOFF_ENVELOPE_KEYS) - set(envelope))
    if extra:
        errors.append(f"handoff envelope has unsupported keys: {extra}")
    if missing:
        errors.append(f"handoff envelope is missing keys: {missing}")
    if envelope.get("schema_version") != HANDOFF_ENVELOPE_SCHEMA_VERSION:
        errors.append("handoff envelope schema_version is invalid")
    _text(envelope.get("objective"), "handoff envelope objective", errors)
    if envelope.get("state") not in HANDOFF_ENVELOPE_STATES:
        errors.append("handoff envelope state is invalid")
    for key in ("decisions", "assumptions", "evidence", "risks", "stop_conditions"):
        _string_list(envelope.get(key), f"handoff envelope {key}", errors)
    _text(envelope.get("next_action"), "handoff envelope next_action", errors)
    boundary = _text(envelope.get("claim_boundary"), "handoff envelope claim_boundary", errors)
    if boundary and "not" not in boundary.casefold():
        errors.append("handoff envelope claim_boundary must state a limitation")
    return errors


def build_handoff_envelope(
    objective: str,
    *,
    state: str = "prepared",
    decisions: list[str] | tuple[str, ...] = (),
    assumptions: list[str] | tuple[str, ...] = (),
    evidence: list[str] | tuple[str, ...] = (),
    risks: list[str] | tuple[str, ...] = (),
    next_action: str,
    stop_conditions: list[str] | tuple[str, ...] = (),
    claim_boundary: str = "A prepared handoff is not execution, review, CI, or completion evidence.",
) -> dict[str, Any]:
    """Build and validate a metadata-safe handoff envelope.

    The objective is represented by a digest and length so wrapper responses do
    not accidentally persist or echo private task text.
    """
    objective_digest = sha256(objective.encode("utf-8")).hexdigest()
    envelope: dict[str, Any] = {
        "schema_version": HANDOFF_ENVELOPE_SCHEMA_VERSION,
        "objective": f"sha256:{objective_digest} length:{len(objective)}",
        "state": state,
        "decisions": list(decisions),
        "assumptions": list(assumptions),
        "evidence": list(evidence),
        "risks": list(risks),
        "next_action": next_action,
        "stop_conditions": list(stop_conditions),
        "claim_boundary": claim_boundary,
    }
    errors = validate_handoff_envelope(envelope)
    if errors:
        raise ValueError("invalid handoff envelope: " + "; ".join(errors))
    return envelope
