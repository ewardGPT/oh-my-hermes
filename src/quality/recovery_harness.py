"""Executable, isolated local crash-recovery self-test."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from ..paths import resolve_paths
from ..runtime.artifacts import create_run
from ..runtime.checkpoints import CheckpointConflict, record_tool_result, resume_checkpoint, save_checkpoint
from .recovery_evaluation import RECOVERY_PHASES, evaluate_recovery_cases


RECOVERY_HARNESS_SCHEMA_VERSION = "recovery_harness/v1"


def run_recovery_self_test() -> dict[str, object]:
    """Exercise checkpoint and replay contracts without external side effects."""
    with TemporaryDirectory(prefix="omh-recovery-self-test-") as tmp:
        paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
        run = create_run(paths, {"skill": "plan", "harness": "coding-handling", "status": "started"})
        run_dir = paths.runtime_runs_dir / str(run["run_id"])
        cases: list[dict[str, object]] = []
        for phase in RECOVERY_PHASES:
            save_checkpoint(
                run_dir,
                phase=phase,
                state={"phase": phase},
                next_action="resume_next",
                idempotency_key=f"self-test-checkpoint-{phase}",
            )
            recovery = resume_checkpoint(run_dir)
            recorded = record_tool_result(
                run_dir,
                idempotency_key=f"self-test-tool-{phase}",
                tool_name="read_status",
                arguments_digest=f"self-test-args-{phase}",
                result={"phase": phase},
            )
            replayed = record_tool_result(
                run_dir,
                idempotency_key=f"self-test-tool-{phase}",
                tool_name="read_status",
                arguments_digest=f"self-test-args-{phase}",
                result={"phase": "different-on-retry"},
            )
            try:
                record_tool_result(
                    run_dir,
                    idempotency_key=f"self-test-tool-{phase}",
                    tool_name="read_status",
                    arguments_digest="different-arguments",
                    result={"phase": phase},
                )
            except CheckpointConflict:
                conflict_refused = True
            else:
                conflict_refused = False
            cases.append(
                {
                    "case_id": phase,
                    "phase": phase,
                    "resume_status": recovery["status"],
                    "next_action": recovery["next_action"],
                    "record_status": recorded["status"],
                    "replay_status": replayed["status"],
                    "conflict_refused": conflict_refused,
                    "side_effect_count": 0,
                }
            )
        evaluation = evaluate_recovery_cases(cases)
    return {
        "schema_version": RECOVERY_HARNESS_SCHEMA_VERSION,
        "mode": "isolated_self_test",
        "cases": cases,
        "evaluation": evaluation,
        "claim_boundary": "This self-test exercises OMH local checkpoint and replay contracts only; it does not invoke external tools, providers, executors, or production state.",
    }
