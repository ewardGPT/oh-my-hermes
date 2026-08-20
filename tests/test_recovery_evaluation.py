from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.paths import resolve_paths
from omh.quality.recovery_evaluation import evaluate_recovery_cases
from omh.quality.recovery_harness import _hung_worker, run_process_crash_self_test, run_recovery_self_test
from omh.runtime.artifacts import create_run
from omh.runtime.checkpoints import CheckpointConflict, record_tool_result, resume_checkpoint, save_checkpoint


RECOVERY_PHASES = ("handoff_prepared", "executor_dispatched", "executor_result", "verification")


def _observed_cases(tmp: str) -> list[dict[str, object]]:
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
            idempotency_key=f"checkpoint-{phase}",
        )
        recovery = resume_checkpoint(run_dir)
        recorded = record_tool_result(
            run_dir,
            idempotency_key=f"tool-{phase}",
            tool_name="read_status",
            arguments_digest=f"args-{phase}",
            result={"phase": phase},
        )
        replayed = record_tool_result(
            run_dir,
            idempotency_key=f"tool-{phase}",
            tool_name="read_status",
            arguments_digest=f"args-{phase}",
            result={"phase": "different-on-retry"},
        )
        try:
            record_tool_result(
                run_dir,
                idempotency_key=f"tool-{phase}",
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
    return cases


class RecoveryEvaluationTests(unittest.TestCase):
    def test_process_crash_self_test_fails_closed_when_worker_ignores_termination(self) -> None:
        result = run_process_crash_self_test(timeout_seconds=1.0, termination_timeout_seconds=0.2, worker_target=_hung_worker)
        self.assertEqual(result["mode"], "process_crash_self_test")
        self.assertEqual(result["status"], "failed")
        self.assertNotEqual(result["worker_exit_code"], 23)
        self.assertEqual(result["worker_cleanup"], "clean")
        self.assertEqual(result["recovery"]["status"], "resumable")
        self.assertEqual(result["record_status"], "not_attempted")
        self.assertEqual(result["replay_status"], "not_attempted")
        self.assertFalse(result["conflict_refused"])

    def test_process_crash_self_test_recovers_from_terminated_worker(self) -> None:
        result = run_process_crash_self_test()
        self.assertEqual(result["mode"], "process_crash_self_test")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["worker_exit_code"], 23)
        self.assertEqual(result["worker_cleanup"], "clean")
        self.assertEqual(result["recovery"]["status"], "resumable")
        self.assertEqual(result["recovery"]["checkpoint"]["phase"], "executor_dispatched")
        self.assertEqual(result["replay_status"], "replayed")
        self.assertTrue(result["conflict_refused"])

    def test_executable_self_test_exercises_all_recovery_phases(self) -> None:
        result = run_recovery_self_test()
        self.assertEqual(result["mode"], "isolated_self_test")
        self.assertEqual(result["evaluation"]["status"], "passed")
        self.assertEqual(result["evaluation"]["observed"]["phase_count"], 4)
        self.assertTrue(all(case["replay_status"] == "replayed" for case in result["cases"]))

    def test_real_checkpoint_and_replay_cases_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            result = evaluate_recovery_cases(_observed_cases(tmp))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["failure_codes"], [])
        self.assertEqual(result["observed"]["phase_count"], 4)

    def test_missing_phase_and_duplicate_side_effect_fail_actionably(self) -> None:
        result = evaluate_recovery_cases(
            [
                {
                    "case_id": "dispatch",
                    "phase": "executor_dispatched",
                    "resume_status": "resumable",
                    "next_action": "resume_next",
                    "record_status": "recorded",
                    "replay_status": "recorded",
                    "conflict_refused": False,
                    "side_effect_count": 1,
                }
            ]
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("missing_handoff_prepared", result["failure_codes"])
        self.assertIn("executor_dispatched_replay_not_observed", result["failure_codes"])
        self.assertIn("executor_dispatched_conflict_not_refused", result["failure_codes"])
        self.assertIn("executor_dispatched_duplicate_side_effect", result["failure_codes"])


if __name__ == "__main__":
    unittest.main()
