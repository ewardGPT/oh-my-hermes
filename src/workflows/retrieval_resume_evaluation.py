"""Privacy-safe evaluator for retrieval and task-resume evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence


RETRIEVAL_RESUME_EVALUATION_SCHEMA_VERSION = "retrieval_resume_evaluation/v1"
HANDOFF_ENVELOPE_SCHEMA_VERSION = "handoff_envelope/v1"


def default_retrieval_resume_cases() -> list[dict[str, object]]:
    """Return the small deterministic smoke corpus used by the CLI."""
    return [
        {
            "case_id": "approved-current-memory",
            "expected_source": "approved-memory",
            "selected_sources": ["approved-memory"],
            "stale_sources": ["stale-memory", "superseded-memory"],
            "resume_state": {
                "schema_version": HANDOFF_ENVELOPE_SCHEMA_VERSION,
                "state": "in_progress",
                "next_action": "verify",
            },
            "token_count": 80,
            "token_budget": 100,
        }
    ]


def run_retrieval_resume_evaluation(cases: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Evaluate supplied benchmark observations without storing query text."""
    rows = [_evaluate_case(case) for case in cases]
    passed = sum(1 for row in rows if row["passed"])
    return {
        "schema_version": RETRIEVAL_RESUME_EVALUATION_SCHEMA_VERSION,
        "case_count": len(rows),
        "passed_count": passed,
        "failed_count": len(rows) - passed,
        "pass_rate_percent": round((passed / len(rows)) * 100, 1) if rows else 0.0,
        "cases": rows,
        "claim_boundary": (
            "This evaluates supplied metadata observations only. It is not proof of retrieval quality, "
            "resume success, token billing, or behavior outside the supplied cases."
        ),
    }


def evaluate_recall_pack(
    pack: Mapping[str, object],
    *,
    expected_source: str,
    stale_source_ids: Sequence[str] = (),
    resume_state: Mapping[str, object] | None = None,
    token_budget: int = 0,
) -> dict[str, object]:
    """Evaluate one real ``build_project_memory_recall_pack`` result.

    The recall implementation owns ranking and eligibility; this adapter only
    projects its metadata into the benchmark contract.
    """
    included = pack.get("included_records")
    records = included if isinstance(included, Sequence) and not isinstance(included, (str, bytes)) else []
    selected = [str(item.get("record_id", "")) for item in records if isinstance(item, Mapping)]
    token_count = sum(max(1, len(str(item.get("summary", ""))) // 4) for item in records if isinstance(item, Mapping))
    return _evaluate_case(
        {
            "case_id": str(pack.get("task_ref", {}).get("sha256", "recall") if isinstance(pack.get("task_ref"), Mapping) else "recall"),
            "expected_source": expected_source,
            "selected_sources": selected,
            "stale_sources": list(stale_source_ids),
            "resume_state": resume_state or {},
            "token_count": token_count,
            "token_budget": token_budget,
        }
    )


def _evaluate_case(case: Mapping[str, object]) -> dict[str, object]:
    case_id = _safe_id(case.get("case_id"))
    expected_source = _safe_id(case.get("expected_source"))
    selected_sources = [_safe_id(value) for value in _strings(case.get("selected_sources"))]
    stale_sources = set(_safe_id(value) for value in _strings(case.get("stale_sources")))
    resume = case.get("resume_state") if isinstance(case.get("resume_state"), Mapping) else {}
    token_count = _non_negative_int(case.get("token_count"))
    token_budget = _non_negative_int(case.get("token_budget"))
    gates = {
        "source_selected": bool(expected_source and selected_sources and selected_sources[0] == expected_source),
        "stale_sources_rejected": stale_sources.isdisjoint(selected_sources),
        "resume_state_valid": _valid_resume_state(resume),
        "token_budget_met": token_count is not None and token_budget is not None and token_count <= token_budget,
    }
    failures = [name for name, passed in gates.items() if not passed]
    safe_case = {"case_id": case_id, "expected_source": expected_source, "selected_sources": selected_sources}
    return {
        "case_id": case_id,
        "case_sha256": hashlib.sha256(json.dumps(safe_case, sort_keys=True).encode("utf-8")).hexdigest(),
        "observed": {
            "selected_source": selected_sources[0] if selected_sources else "",
            "stale_source_count": len(stale_sources),
            "token_count": token_count,
        },
        "gates": gates,
        "passed": not failures,
        "failure_codes": failures,
    }


def _valid_resume_state(state: Mapping[str, object]) -> bool:
    return (
        state.get("schema_version") == HANDOFF_ENVELOPE_SCHEMA_VERSION
        and state.get("state") in {"prepared", "in_progress", "blocked", "completed"}
        and isinstance(state.get("next_action"), str)
        and bool(str(state.get("next_action", "")).strip())
    )


def _safe_id(value: object) -> str:
    return " ".join(str(value or "").split())[:120]


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _non_negative_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value
