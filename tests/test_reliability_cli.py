from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()


class ReliabilityCliTests(unittest.TestCase):
    def test_trajectory_command_emits_evaluation(self) -> None:
        events = [{"stage": stage, "source": "journal", "ref": f"journal:{stage}:1"} for stage in ("request", "route", "memory", "result", "recovery", "approval", "verification", "outcome")]
        events[4]["status"] = "not_needed"
        events[5]["status"] = "approved"
        events.append({"stage": "tool", "source": "tool", "ref": "tool:1", "choice": "appropriate", "safety": "safe"})
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "trajectory.json"
            path.write_text(json.dumps(events), encoding="utf-8")
            status, stdout, _stderr = run_cli(["reliability", "trajectory", "--input", str(path)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["status"], "passed")

    def test_slo_command_reports_unknown_empty_input(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "slos.json"
            path.write_text("[]", encoding="utf-8")
            status, stdout, _stderr = run_cli(["reliability", "slos", "--input", str(path)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["metrics"]["cost_usd"]["state"], "unknown")

    def test_recovery_command_emits_evaluation(self) -> None:
        cases = [
            {
                "case_id": phase,
                "phase": phase,
                "resume_status": "resumable",
                "next_action": "resume_next",
                "record_status": "recorded",
                "replay_status": "replayed",
                "conflict_refused": True,
                "side_effect_count": 0,
            }
            for phase in ("handoff_prepared", "executor_dispatched", "executor_result", "verification")
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recovery.json"
            path.write_text(json.dumps(cases), encoding="utf-8")
            status, stdout, _stderr = run_cli(["reliability", "recovery", "--input", str(path)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["status"], "passed")


if __name__ == "__main__":
    unittest.main()
