"""Privacy-safe trajectory evaluation over normalized agent lifecycle events."""

from __future__ import annotations

from typing import Final, Mapping


TRAJECTORY_EVALUATION_SCHEMA_VERSION: Final = "trajectory_evaluation/v1"
REQUIRED_STAGES: Final = ("request", "route", "memory", "tool", "result", "recovery", "approval", "verification", "outcome")


def evaluate_trajectory(events: list[Mapping[str, object]] | tuple[Mapping[str, object], ...]) -> dict[str, object]:
    if not isinstance(events, (list, tuple)):
        raise ValueError("trajectory events must be a list")
    stages: dict[str, Mapping[str, object]] = {}
    errors: list[str] = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            errors.append(f"event_{index}_not_object")
            continue
        stage = str(event.get("stage", ""))
        source = str(event.get("source", ""))
        ref = str(event.get("ref", ""))
        if stage not in REQUIRED_STAGES:
            errors.append(f"event_{index}_unknown_stage")
        elif not source or not ref or any(token in ref.casefold() for token in ("prompt", "secret", "token", "password")):
            errors.append(f"event_{index}_unsafe_or_missing_ref")
        elif stage in stages:
            errors.append(f"duplicate_stage_{stage}")
        else:
            stages[stage] = event
    missing = [stage for stage in REQUIRED_STAGES if stage not in stages]
    failures = [f"missing_{stage}" for stage in missing] + errors
    tool_choice = _value(stages.get("tool"), "choice")
    recovery = _value(stages.get("recovery"), "status")
    safety = _value(stages.get("approval"), "status") in {"approved", "not_required"} and _value(stages.get("tool"), "safety") in {"safe", "not_applicable"}
    return {
        "schema_version": TRAJECTORY_EVALUATION_SCHEMA_VERSION,
        "status": "passed" if not failures and tool_choice in {"appropriate", "not_applicable"} and recovery in {"not_needed", "completed"} and safety else "failed",
        "stage_count": len(stages),
        "missing_stages": missing,
        "failure_codes": failures + ([] if tool_choice in {"appropriate", "not_applicable"} else ["tool_choice_not_appropriate"]) + ([] if recovery in {"not_needed", "completed"} else ["recovery_incomplete"]) + ([] if safety else ["safety_or_approval_not_verified"]),
        "observed": {"stages": sorted(stages), "tool_choice": tool_choice, "recovery": recovery, "safety": safety},
        "claim_boundary": "This evaluates supplied metadata event references only; it is not proof of raw tool content, model quality, user satisfaction, or unrecorded side effects.",
    }


def _value(event: Mapping[str, object] | None, key: str) -> str:
    return str(event.get(key, "")) if isinstance(event, Mapping) else ""
