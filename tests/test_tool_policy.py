from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.runtime.tool_policy import build_tool_policy, decide_tool_call, validate_tool_policy  # noqa: E402


class ToolPolicyTests(unittest.TestCase):
    def test_read_tool_is_allowable_and_retryable(self) -> None:
        policy = build_tool_policy("status", capability="read_status")
        self.assertEqual(decide_tool_call(policy, attempt=2, budget_remaining=1)["action"], "allow")

    def test_mutating_tool_requires_authority_and_approval(self) -> None:
        policy = build_tool_policy("publish", capability="publish", side_effect="external", idempotent=True, authority_scope="operator", approval_required=True, compensation="rollback")
        self.assertEqual(decide_tool_call(policy, authority_granted=True, budget_remaining=1)["reason"], "approval_required")
        self.assertEqual(decide_tool_call(policy, authority_granted=True, approved=True, budget_remaining=1)["action"], "allow")

    def test_invalid_policy_and_budget_fail_closed(self) -> None:
        policy = build_tool_policy("read", capability="read")
        self.assertEqual(decide_tool_call(policy, budget_remaining=0)["reason"], "budget_exceeded")
        forged = {**policy, "side_effect": "external", "approval_required": False}
        self.assertTrue(validate_tool_policy(forged))


if __name__ == "__main__":
    unittest.main()
