"""Executable, isolated local crash-recovery self-test."""

from __future__ import annotations

import multiprocessing
import os
import signal
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from ..paths import resolve_paths
from ..runtime.artifacts import create_run
from ..runtime.checkpoints import CheckpointConflict, record_tool_result, resume_checkpoint, save_checkpoint
from .recovery_evaluation import RECOVERY_PHASES, evaluate_recovery_cases


RECOVERY_HARNESS_SCHEMA_VERSION = "recovery_harness/v1"


def _crash_worker(omh_home: str, hermes_home: str, run_id: str) -> None:
    """Persist a dispatch checkpoint, then simulate an abrupt worker death."""
    paths = resolve_paths(Path(omh_home), Path(hermes_home))
    run_dir = paths.runtime_runs_dir / run_id
    save_checkpoint(
        run_dir,
        phase="executor_dispatched",
        state={"phase": "executor_dispatched"},
        next_action="resume_next",
        idempotency_key="process-crash-checkpoint",
    )
    os._exit(23)


def _hung_worker(omh_home: str, hermes_home: str, run_id: str) -> None:
    """Persist a checkpoint and ignore graceful termination for failure tests."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    paths = resolve_paths(Path(omh_home), Path(hermes_home))
    save_checkpoint(
        paths.runtime_runs_dir / run_id,
        phase="executor_dispatched",
        state={"phase": "executor_dispatched"},
        next_action="resume_next",
        idempotency_key="process-crash-checkpoint",
    )
    while True:
        time.sleep(1)


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


def run_process_crash_self_test(
    *,
    worker_target: Callable[[str, str, str], None] = _crash_worker,
    timeout_seconds: float = 10,
    termination_timeout_seconds: float = 2,
) -> dict[str, object]:
    """Verify checkpoint recovery after a worker process terminates abruptly."""
    with TemporaryDirectory(prefix="omh-process-crash-self-test-") as tmp:
        root = Path(tmp)
        paths = resolve_paths(root / ".omh", root / ".hermes")
        run = create_run(paths, {"skill": "plan", "harness": "process-crash", "status": "started"})
        run_id = str(run["run_id"])
        run_dir = paths.runtime_runs_dir / run_id
        context = multiprocessing.get_context("spawn")
        worker = context.Process(
            target=worker_target,
            args=(str(paths.omh_home), str(paths.hermes_home), run_id),
        )
        worker.start()
        worker.join(timeout=timeout_seconds)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=termination_timeout_seconds)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=termination_timeout_seconds)

        worker_exit_code = worker.exitcode
        worker_cleanup = "clean" if not worker.is_alive() else "leaked"
        recovery = resume_checkpoint(run_dir)
        replay_status = "not_attempted"
        conflict_refused = False
        record_status = "not_attempted"
        if worker_exit_code == 23 and recovery.get("status") == "resumable":
            recorded = record_tool_result(
                run_dir,
                idempotency_key="process-crash-tool",
                tool_name="read_status",
                arguments_digest="process-crash-args",
                result={"recovered": True},
            )
            record_status = str(recorded.get("status"))
            replayed = record_tool_result(
                run_dir,
                idempotency_key="process-crash-tool",
                tool_name="read_status",
                arguments_digest="process-crash-args",
                result={"recovered": False},
            )
            replay_status = str(replayed.get("status"))
            try:
                record_tool_result(
                    run_dir,
                    idempotency_key="process-crash-tool",
                    tool_name="read_status",
                    arguments_digest="different-process-crash-args",
                    result={"recovered": True},
                )
            except CheckpointConflict:
                conflict_refused = True

        passed = (
            worker_exit_code == 23
            and recovery.get("status") == "resumable"
            and isinstance(recovery.get("checkpoint"), dict)
            and recovery["checkpoint"].get("phase") == "executor_dispatched"
            and worker_cleanup == "clean"
            and record_status == "recorded"
            and replay_status == "replayed"
            and conflict_refused
        )
    return {
        "schema_version": RECOVERY_HARNESS_SCHEMA_VERSION,
        "mode": "process_crash_self_test",
        "status": "passed" if passed else "failed",
        "worker_exit_code": worker_exit_code,
        "worker_cleanup": worker_cleanup,
        "recovery": recovery,
        "record_status": record_status,
        "replay_status": replay_status,
        "conflict_refused": conflict_refused,
        "claim_boundary": "This self-test proves local checkpoint persistence and replay behavior across an abruptly terminated worker process; it does not prove external tool side effects are transactional or recoverable.",
    }
