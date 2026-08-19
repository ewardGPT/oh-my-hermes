from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.runtime.verification_gate import (  # noqa: E402
    VERIFICATION_GATE_SCHEMA_VERSION,
    evaluate_verification_gate,
    validate_verification_gate,
)


class VerificationGateTests(unittest.TestCase):
    def test_prepared_handoff_cannot_claim_execution(self) -> None:
        gate = evaluate_verification_gate("execution", {"handoff_envelope_valid": True})

        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(gate["missing_evidence"], ["runtime_observed", "correlation_id"])
        self.assertEqual(validate_verification_gate(gate), [])

    def test_complete_evidence_advances_each_stage(self) -> None:
        evidence = {
            "handoff_envelope_valid": True,
            "runtime_observed": True,
            "correlation_id": "corr-123",
            "test_status": "passed",
            "test_evidence_ref": "test-run-1",
            "review_status": "approved",
            "review_evidence_ref": "review-1",
        }

        tests_gate = evaluate_verification_gate("tests", evidence)
        review_gate = evaluate_verification_gate("review", evidence)

        self.assertEqual(tests_gate["status"], "passed")
        self.assertEqual(tests_gate["next_stage"], "review")
        self.assertEqual(review_gate["status"], "passed")
        self.assertIsNone(review_gate["next_stage"])

    def test_tampering_with_passed_gate_is_rejected(self) -> None:
        gate = evaluate_verification_gate("handoff", {"handoff_envelope_valid": True})
        gate["missing_evidence"] = ["fake"]

        errors = validate_verification_gate(gate)

        self.assertEqual(gate["schema_version"], VERIFICATION_GATE_SCHEMA_VERSION)
        self.assertIn("passed gate must have no missing evidence", errors)


if __name__ == "__main__":
    unittest.main()
