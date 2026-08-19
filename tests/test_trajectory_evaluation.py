from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.quality.trajectory_evaluation import evaluate_trajectory  # noqa: E402


def _events() -> list[dict[str, object]]:
    events = [{"stage": stage, "source": "journal", "ref": f"journal:{stage}:1"} for stage in ("request", "route", "memory", "result", "recovery", "approval", "verification", "outcome")]
    events[4]["status"] = "not_needed"
    events[5]["status"] = "approved"
    return events + [{"stage": "tool", "source": "tool-observer", "ref": "tool:1", "choice": "appropriate", "safety": "safe"}]


class TrajectoryEvaluationTests(unittest.TestCase):
    def test_complete_safe_trajectory_passes(self) -> None:
        result = evaluate_trajectory(_events())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["failure_codes"], [])

    def test_missing_recovery_and_unsafe_reference_fail_actionably(self) -> None:
        events = [event for event in _events() if event["stage"] != "recovery"]
        events[0] = {**events[0], "ref": "secret prompt text"}
        result = evaluate_trajectory(events)
        self.assertEqual(result["status"], "failed")
        self.assertIn("missing_recovery", result["failure_codes"])
        self.assertIn("event_0_unsafe_or_missing_ref", result["failure_codes"])


if __name__ == "__main__":
    unittest.main()
