"""Deterministic context-budget decisions for long-running agent turns."""

from __future__ import annotations

from typing import Final, Mapping


CONTEXT_GOVERNOR_SCHEMA_VERSION: Final = "context_governor/v1"
REASONS: Final = ("within_budget", "reserve_protected", "tool_result_cleared", "memory_admission_rejected", "compaction_required", "replay_over_budget")


def govern_context(*, total_budget: int, system_tokens: int, handoff_reserve: int, memory_tokens: int, tool_result_tokens: int, durable_tokens: int = 0, replay: bool = False) -> dict[str, object]:
    values = (total_budget, system_tokens, handoff_reserve, memory_tokens, tool_result_tokens, durable_tokens)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values) or total_budget < 1:
        raise ValueError("context budgets must be non-negative integers and total_budget must be positive")
    used = system_tokens + handoff_reserve + memory_tokens + tool_result_tokens + durable_tokens
    available = max(0, total_budget - system_tokens - handoff_reserve)
    overflow = max(0, used - total_budget)
    if replay and overflow:
        reason = "replay_over_budget"
    elif overflow and tool_result_tokens:
        reason = "tool_result_cleared"
    elif overflow and memory_tokens:
        reason = "memory_admission_rejected"
    elif overflow:
        reason = "compaction_required"
    else:
        reason = "within_budget"
    return {
        "schema_version": CONTEXT_GOVERNOR_SCHEMA_VERSION,
        "status": "blocked" if reason in {"reserve_protected", "replay_over_budget"} else ("degrade" if reason != "within_budget" else "allow"),
        "reason": reason,
        "total_budget": total_budget,
        "used_tokens": used,
        "available_payload_tokens": available,
        "overflow_tokens": overflow,
        "reserved_tokens": system_tokens + handoff_reserve,
        "actions": _actions(reason),
        "claim_boundary": "This is a deterministic budget projection, not a provider billing record or proof that compaction preserved task quality.",
    }


def validate_context_governor(decision: Mapping[str, object] | object) -> list[str]:
    if not isinstance(decision, Mapping):
        return ["decision must be an object"]
    errors: list[str] = []
    if decision.get("schema_version") != CONTEXT_GOVERNOR_SCHEMA_VERSION:
        errors.append("schema_version is invalid")
    if decision.get("reason") not in REASONS:
        errors.append("reason is invalid")
    if not isinstance(decision.get("actions"), list) or not all(isinstance(item, str) for item in decision.get("actions", [])):
        errors.append("actions must be a string list")
    if "not" not in str(decision.get("claim_boundary", "")).casefold():
        errors.append("claim_boundary must state a limitation")
    return errors


def _actions(reason: str) -> list[str]:
    return {
        "within_budget": [],
        "tool_result_cleared": ["clear_low_signal_tool_results", "recheck_budget"],
        "memory_admission_rejected": ["reject_low_priority_memory", "recheck_budget"],
        "compaction_required": ["compact_durable_context", "recheck_budget"],
        "replay_over_budget": ["stop_replay", "request_fresh_handoff"],
        "reserve_protected": ["stop_before_handoff_reserve"],
    }[reason]
