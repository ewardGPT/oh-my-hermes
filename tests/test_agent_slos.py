from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.runtime.agent_slos import project_agent_slos  # noqa: E402


class AgentSloTests(unittest.TestCase):
    def test_projects_success_recovery_cost_latency_and_escalation(self) -> None:
        result = project_agent_slos([
            {"outcome": "completed", "recovery": "completed", "evidence_complete": True, "latency_ms": 100, "cost_usd": 0.2, "escalated": False},
            {"outcome": "failed", "recovery": "completed", "evidence_complete": False, "latency_ms": 300, "cost_usd": 0.4, "escalated": True},
        ])
        self.assertEqual(result["metrics"]["success_rate"]["value"], 0.5)
        self.assertEqual(result["metrics"]["recovery_rate"]["value"], 1.0)
        self.assertEqual(result["threshold_status"], {"latency": "within", "cost": "within"})

    def test_missing_observations_are_unknown_not_zero(self) -> None:
        result = project_agent_slos([])
        self.assertEqual(result["metrics"]["success_rate"]["state"], "unknown")
        self.assertEqual(result["metrics"]["cost_usd"]["value"], None)
        self.assertEqual(result["threshold_status"]["latency"], "unknown")


if __name__ == "__main__":
    unittest.main()
