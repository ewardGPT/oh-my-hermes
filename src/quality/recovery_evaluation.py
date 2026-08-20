"""Metadata-only evaluation of crash recovery and replay safety."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final


RECOVERY_EVALUATION_SCHEMA_VERSION: Final = "recovery_evaluation/v1"
RECOVERY_PHASES: Final = ("handoff_prepared", "executor_dispatched", "executor_result", "verification")


def evaluate_recovery_cases(cases: list[Mapping[str, object]] | tuple[Mapping[str, object], ...]) -> dict[str, object]:
    if not isinstance(cases, (list, tuple)):
        raise ValueError("recovery cases must be a list")
    seen: dict[str, Mapping[str, object]] = {}
    errors: list[str] = []
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append(f"case_{index}_not_object")
            continue
        phase = str(case.get("phase", ""))
        if phase not in RECOVERY_PHASES:
            errors.append(f"case_{index}_unknown_phase")
            continue
        if phase in seen:
            errors.append(f"duplicate_phase_{phase}")
            continue
        seen[phase] = case
        if not str(case.get("case_id", "")).strip():
            errors.append(f"case_{index}_missing_case_id")
        if not str(case.get("next_action", "")).strip():
            errors.append(f"case_{index}_missing_next_action")
        if case.get("resume_status") != "resumable":
            errors.append(f"{phase}_not_resumable")
        if case.get("record_status") != "recorded":
            errors.append(f"{phase}_record_not_observed")
        if case.get("replay_status") != "replayed":
            errors.append(f"{phase}_replay_not_observed")
        if case.get("conflict_refused") is not True:
            errors.append(f"{phase}_conflict_not_refused")
        side_effect_count = case.get("side_effect_count")
        if isinstance(side_effect_count, bool) or not isinstance(side_effect_count, int) or side_effect_count != 0:
            errors.append(f"{phase}_duplicate_side_effect")
    missing = [phase for phase in RECOVERY_PHASES if phase not in seen]
    failures = [f"missing_{phase}" for phase in missing] + errors
    return {
        "schema_version": RECOVERY_EVALUATION_SCHEMA_VERSION,
        "status": "passed" if not failures else "failed",
        "case_count": len(seen),
        "missing_phases": missing,
        "failure_codes": failures,
        "observed": {
            "phases": sorted(seen),
            "phase_count": len(seen),
            "replay_safe": not any(code.endswith("_replay_not_observed") for code in failures),
            "conflicts_refused": not any(code.endswith("_conflict_not_refused") for code in failures),
            "side_effect_free_replay": not any(code.endswith("_duplicate_side_effect") for code in failures),
        },
        "claim_boundary": "This evaluates supplied recovery metadata only; it does not execute tools, prove provider behavior, or establish that an unrecorded side effect did not occur.",
    }
