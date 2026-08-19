from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.workflows.retrieval_resume_evaluation import (  # noqa: E402
    HANDOFF_ENVELOPE_SCHEMA_VERSION,
    default_retrieval_resume_cases,
    evaluate_recall_pack,
    run_retrieval_resume_evaluation,
)
from omh.paths import resolve_paths  # noqa: E402
from omh.memory import (  # noqa: E402
    approve_project_memory_candidate,
    build_project_memory_recall_pack,
    capture_project_memory_candidate,
)


class RetrievalResumeEvaluationTests(unittest.TestCase):
    def _resume(self) -> dict[str, object]:
        return {
            "schema_version": HANDOFF_ENVELOPE_SCHEMA_VERSION,
            "state": "in_progress",
            "next_action": "verify",
        }

    def test_report_passes_valid_retrieval_resume_case(self) -> None:
        report = run_retrieval_resume_evaluation(
            [
                {
                    "case_id": "case-1",
                    "expected_source": "approved-memory",
                    "selected_sources": ["approved-memory"],
                    "stale_sources": ["stale-memory"],
                    "resume_state": self._resume(),
                    "token_count": 80,
                    "token_budget": 100,
                }
            ]
        )

        self.assertEqual(report["passed_count"], 1)
        self.assertTrue(report["cases"][0]["passed"])
        self.assertNotIn("approved-memory", report["cases"][0]["case_sha256"])

    def test_report_surfaces_actionable_failures(self) -> None:
        report = run_retrieval_resume_evaluation(
            [
                {
                    "case_id": "case-2",
                    "expected_source": "current-memory",
                    "selected_sources": ["stale-memory"],
                    "stale_sources": ["stale-memory"],
                    "resume_state": {"state": "in_progress"},
                    "token_count": 101,
                    "token_budget": 100,
                }
            ]
        )

        row = report["cases"][0]
        self.assertFalse(row["passed"])
        self.assertEqual(
            row["failure_codes"],
            ["source_selected", "stale_sources_rejected", "resume_state_valid", "token_budget_met"],
        )

    def test_empty_benchmark_is_explicitly_not_passing(self) -> None:
        report = run_retrieval_resume_evaluation([])

        self.assertEqual(report["pass_rate_percent"], 0.0)
        self.assertEqual(report["case_count"], 0)

    def test_default_smoke_corpus_passes(self) -> None:
        report = run_retrieval_resume_evaluation(default_retrieval_resume_cases())

        self.assertEqual(report["passed_count"], report["case_count"])

    def test_real_recall_pack_projection_uses_included_record_metadata(self) -> None:
        result = evaluate_recall_pack(
            {
                "task_ref": {"sha256": "query-digest"},
                "included_records": [{"record_id": "record-current", "summary": "Use the current policy."}],
            },
            expected_source="record-current",
            stale_source_ids=["record-stale"],
            resume_state=self._resume(),
            token_budget=100,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["observed"]["selected_source"], "record-current")

    def test_actual_reviewed_memory_recall_passes_the_projection_gate(self) -> None:
        with TemporaryDirectory() as temporary:
            paths = resolve_paths(Path(temporary) / ".omh", Path(temporary) / ".hermes")
            captured = capture_project_memory_candidate(paths, "Current policy uses the staging cluster", tags=["policy"])
            approve_project_memory_candidate(paths, str(captured["candidate"]["candidate_id"]))
            pack = build_project_memory_recall_pack(paths, "current policy staging", limit=1)

            result = evaluate_recall_pack(
                pack,
                expected_source=str(pack["included_records"][0]["record_id"]),
                resume_state=self._resume(),
                token_budget=100,
            )

            self.assertTrue(result["passed"], result)


if __name__ == "__main__":
    unittest.main()
