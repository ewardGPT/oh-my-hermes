from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.handoff_envelope import (  # noqa: E402
    HANDOFF_ENVELOPE_SCHEMA_VERSION,
    build_handoff_envelope,
    validate_handoff_envelope,
)


class HandoffEnvelopeTests(unittest.TestCase):
    def test_build_is_metadata_safe_and_versioned(self) -> None:
        envelope = build_handoff_envelope(
            "private task text",
            decisions=["accepted"],
            next_action="verify",
        )

        self.assertEqual(envelope["schema_version"], HANDOFF_ENVELOPE_SCHEMA_VERSION)
        self.assertTrue(str(envelope["objective"]).startswith("sha256:"))
        self.assertNotIn("private task text", str(envelope))
        self.assertEqual(validate_handoff_envelope(envelope), [])

    def test_validator_rejects_missing_and_unknown_fields(self) -> None:
        envelope = build_handoff_envelope("task", next_action="verify")
        envelope.pop("risks")
        envelope["unexpected"] = True

        errors = validate_handoff_envelope(envelope)

        self.assertTrue(any("unsupported keys" in error for error in errors))
        self.assertTrue(any("missing keys" in error for error in errors))

    def test_invalid_state_and_non_limiting_claim_boundary_are_rejected(self) -> None:
        envelope = build_handoff_envelope("task", next_action="verify")
        envelope["state"] = "running"
        envelope["claim_boundary"] = "This proves completion."

        errors = validate_handoff_envelope(envelope)

        self.assertTrue(any("state is invalid" in error for error in errors))
        self.assertTrue(any("claim_boundary must state a limitation" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
