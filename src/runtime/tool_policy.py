"""One metadata-only policy for tool capability and external side effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping


TOOL_POLICY_SCHEMA_VERSION: Final = "tool_policy/v1"
SIDE_EFFECTS: Final = ("none", "read", "write", "external")
AUTHORITY_SCOPES: Final = ("none", "task", "operator", "system")
SENSITIVITY_LEVELS: Final = ("public", "internal", "sensitive", "secret")
RETRY_MODES: Final = ("never", "idempotent_only", "safe")


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    name: str
    capability: str
    side_effect: str
    idempotent: bool
    authority_scope: str
    sensitivity: str
    retry_mode: str
    approval_required: bool
    timeout_seconds: int
    budget_units: int
    compensation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": TOOL_POLICY_SCHEMA_VERSION,
            "name": self.name,
            "capability": self.capability,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
            "authority_scope": self.authority_scope,
            "sensitivity": self.sensitivity,
            "retry_mode": self.retry_mode,
            "approval_required": self.approval_required,
            "timeout_seconds": self.timeout_seconds,
            "budget_units": self.budget_units,
            "compensation": self.compensation,
        }


def validate_tool_policy(policy: Mapping[str, object] | object) -> list[str]:
    if not isinstance(policy, Mapping):
        return ["tool policy must be an object"]
    required = {"schema_version", "name", "capability", "side_effect", "idempotent", "authority_scope", "sensitivity", "retry_mode", "approval_required", "timeout_seconds", "budget_units", "compensation"}
    errors: list[str] = []
    if set(policy) != required:
        errors.append("tool policy fields are not exact")
    if policy.get("schema_version") != TOOL_POLICY_SCHEMA_VERSION:
        errors.append("schema_version is invalid")
    for key in ("name", "capability", "compensation"):
        if not isinstance(policy.get(key), str) or not str(policy.get(key)).strip():
            errors.append(f"{key} must be non-empty")
    if policy.get("side_effect") not in SIDE_EFFECTS:
        errors.append("side_effect is invalid")
    if policy.get("authority_scope") not in AUTHORITY_SCOPES:
        errors.append("authority_scope is invalid")
    if policy.get("sensitivity") not in SENSITIVITY_LEVELS:
        errors.append("sensitivity is invalid")
    if policy.get("retry_mode") not in RETRY_MODES:
        errors.append("retry_mode is invalid")
    for key in ("idempotent", "approval_required"):
        if not isinstance(policy.get(key), bool):
            errors.append(f"{key} must be boolean")
    for key in ("timeout_seconds", "budget_units"):
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"{key} must be a positive integer")
    if policy.get("side_effect") in {"write", "external"} and policy.get("authority_scope") == "none":
        errors.append("mutating tools require authority")
    if policy.get("retry_mode") == "idempotent_only" and policy.get("idempotent") is not True:
        errors.append("idempotent_only retry requires idempotent tool")
    if policy.get("side_effect") == "external" and policy.get("approval_required") is not True:
        errors.append("external tools require approval")
    return errors


def build_tool_policy(name: str, *, capability: str, side_effect: str = "none", idempotent: bool = True, authority_scope: str = "none", sensitivity: str = "internal", retry_mode: str = "idempotent_only", approval_required: bool = False, timeout_seconds: int = 30, budget_units: int = 1, compensation: str = "none") -> dict[str, object]:
    policy = {"schema_version": TOOL_POLICY_SCHEMA_VERSION, "name": name, "capability": capability, "side_effect": side_effect, "idempotent": idempotent, "authority_scope": authority_scope, "sensitivity": sensitivity, "retry_mode": retry_mode, "approval_required": approval_required, "timeout_seconds": timeout_seconds, "budget_units": budget_units, "compensation": compensation}
    errors = validate_tool_policy(policy)
    if errors:
        raise ValueError("invalid tool policy: " + "; ".join(errors))
    return policy


def decide_tool_call(policy: Mapping[str, object], *, authority_granted: bool = False, approved: bool = False, attempt: int = 1, budget_remaining: int = 0) -> dict[str, object]:
    errors = validate_tool_policy(policy)
    if errors:
        return {"schema_version": "tool_decision/v1", "action": "block", "reason": "invalid_policy", "errors": errors}
    if int(policy["budget_units"]) > budget_remaining:
        reason = "budget_exceeded"
    elif policy["authority_scope"] != "none" and not authority_granted:
        reason = "authority_required"
    elif bool(policy["approval_required"]) and not approved:
        reason = "approval_required"
    elif attempt > 1 and policy["retry_mode"] == "never":
        reason = "retry_forbidden"
    elif attempt > 1 and policy["retry_mode"] == "idempotent_only" and not bool(policy["idempotent"]):
        reason = "retry_not_idempotent"
    else:
        return {"schema_version": "tool_decision/v1", "action": "allow", "reason": "policy_satisfied", "budget_units": int(policy["budget_units"])}
    return {"schema_version": "tool_decision/v1", "action": "block", "reason": reason, "budget_units": int(policy["budget_units"])}
