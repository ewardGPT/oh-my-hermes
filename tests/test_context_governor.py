from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.runtime.context_governor import govern_context, validate_context_governor  # noqa: E402


class ContextGovernorTests(unittest.TestCase):
    def test_budgeted_turn_allows_and_protects_reserve(self) -> None:
        decision = govern_context(total_budget=1000, system_tokens=200, handoff_reserve=200, memory_tokens=100, tool_result_tokens=100)
        self.assertEqual(decision["status"], "allow")
        self.assertEqual(decision["reserved_tokens"], 400)
        self.assertEqual(validate_context_governor(decision), [])

    def test_overflow_clears_tool_results_before_memory(self) -> None:
        decision = govern_context(total_budget=1000, system_tokens=200, handoff_reserve=200, memory_tokens=100, tool_result_tokens=700)
        self.assertEqual(decision["reason"], "tool_result_cleared")
        self.assertEqual(decision["actions"][0], "clear_low_signal_tool_results")

    def test_replay_overflow_stops_and_requests_fresh_handoff(self) -> None:
        decision = govern_context(total_budget=100, system_tokens=20, handoff_reserve=30, memory_tokens=60, tool_result_tokens=20, replay=True)
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "replay_over_budget")
        self.assertIn("request_fresh_handoff", decision["actions"])


if __name__ == "__main__":
    unittest.main()
