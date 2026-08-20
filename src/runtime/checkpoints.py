"""Crash-safe runtime checkpoints and idempotent tool-result replay."""

from __future__ import annotations

import hashlib
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ..local_store import locked_json_update, read_json_object


CHECKPOINT_SCHEMA_VERSION = "runtime_checkpoint/v1"
REPLAY_SCHEMA_VERSION = "runtime_tool_replay/v1"


class CheckpointConflict(ValueError):
    """Raised when a replay key is reused for different work."""


def _checkpoint_path(run_dir: Path) -> Path:
    return run_dir / "checkpoint.json"


def _replay_path(run_dir: Path) -> Path:
    return run_dir / "tool_replay.json"


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


def save_checkpoint(
    run_dir: Path,
    *,
    phase: str,
    state: dict[str, Any],
    next_action: str,
    idempotency_key: str,
    status: str = "ready",
) -> dict[str, Any]:
    """Persist the latest resumable state exactly once per idempotency key."""
    phase = _require_text(phase, "phase")
    next_action = _require_text(next_action, "next_action")
    idempotency_key = _require_text(idempotency_key, "idempotency_key")
    if status not in {"ready", "completed", "blocked"}:
        raise ValueError("status must be ready, completed, or blocked")
    try:
        state_copy = json.loads(json.dumps(state, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("state must contain JSON-serializable values") from exc
    if not isinstance(state_copy, dict):
        raise ValueError("state must be a JSON object")
    path = _checkpoint_path(run_dir)
    state_digest = _digest(state_copy)

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        existing = current.get("checkpoint")
        if isinstance(existing, dict) and existing.get("idempotency_key") == idempotency_key:
            if (
                existing.get("state_digest") != state_digest
                or existing.get("phase") != phase
                or existing.get("next_action") != next_action
                or existing.get("status") != status
            ):
                raise CheckpointConflict("checkpoint idempotency key was reused for different state")
            return current
        sequence = int(existing.get("sequence", 0)) + 1 if isinstance(existing, dict) else 1
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "checkpoint": {
                "run_id": run_dir.name,
                "sequence": sequence,
                "phase": phase,
                "status": status,
                "state": state_copy,
                "state_digest": state_digest,
                "next_action": next_action,
                "idempotency_key": idempotency_key,
            },
        }

    updated = locked_json_update(path, mutate, default={}, private=True)
    checkpoint = updated.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint store did not contain a checkpoint")
    return checkpoint


def read_checkpoint(run_dir: Path) -> dict[str, Any] | None:
    try:
        stored = read_json_object(_checkpoint_path(run_dir))
    except (OSError, JSONDecodeError, ValueError):
        return None
    if not isinstance(stored, dict):
        return None
    checkpoint = stored.get("checkpoint")
    return dict(checkpoint) if isinstance(checkpoint, dict) else None


def resume_checkpoint(run_dir: Path) -> dict[str, Any]:
    checkpoint_path = _checkpoint_path(run_dir)
    try:
        checkpoint = read_checkpoint(run_dir)
    except (OSError, JSONDecodeError, ValueError) as exc:
        return {
            "schema_version": "runtime_resume/v1",
            "status": "checkpoint_corrupt",
            "checkpoint": None,
            "next_action": "inspect_run",
            "error": str(exc),
            "claim_boundary": "The checkpoint could not be parsed; no prior work is replayed or inferred.",
        }
    if checkpoint is None and checkpoint_path.exists():
        return {
            "schema_version": "runtime_resume/v1",
            "status": "checkpoint_corrupt",
            "checkpoint": None,
            "next_action": "inspect_run",
            "claim_boundary": "The checkpoint could not be parsed; no prior work is replayed or inferred.",
        }
    if checkpoint is None:
        return {
            "schema_version": "runtime_resume/v1",
            "status": "no_checkpoint",
            "checkpoint": None,
            "next_action": "start_run",
            "claim_boundary": "No durable checkpoint was observed; no prior work is replayed or inferred.",
        }
    status = str(checkpoint.get("status", "ready"))
    resumable = status == "ready"
    return {
        "schema_version": "runtime_resume/v1",
        "status": "resumable" if resumable else "not_resumable",
        "checkpoint": checkpoint,
        "next_action": checkpoint.get("next_action", "") if resumable else "inspect_run",
        "claim_boundary": "Resume points to the last atomically persisted checkpoint; it does not prove the interrupted step completed.",
    }


def record_tool_result(
    run_dir: Path,
    *,
    idempotency_key: str,
    tool_name: str,
    arguments_digest: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Record a tool result, or return the original result on safe replay."""
    idempotency_key = _require_text(idempotency_key, "idempotency_key")
    tool_name = _require_text(tool_name, "tool_name")
    arguments_digest = _require_text(arguments_digest, "arguments_digest")
    try:
        result_copy = json.loads(json.dumps(result, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("result must contain JSON-serializable values") from exc
    if not isinstance(result_copy, dict):
        raise ValueError("result must be a JSON object")

    replayed = False

    def mutate(current: dict[str, Any]) -> dict[str, Any]:
        nonlocal replayed
        entries = current.get("entries")
        entries = dict(entries) if isinstance(entries, dict) else {}
        existing = entries.get(idempotency_key)
        if isinstance(existing, dict):
            replayed = True
            if existing.get("tool_name") != tool_name or existing.get("arguments_digest") != arguments_digest:
                raise CheckpointConflict("tool idempotency key was reused for different arguments")
            return current
        entries[idempotency_key] = {
            "tool_name": tool_name,
            "arguments_digest": arguments_digest,
            "result": result_copy,
        }
        return {"schema_version": REPLAY_SCHEMA_VERSION, "entries": entries}

    updated = locked_json_update(_replay_path(run_dir), mutate, default={"schema_version": REPLAY_SCHEMA_VERSION}, private=True)
    entry = updated.get("entries", {}).get(idempotency_key)
    if not isinstance(entry, dict):
        raise ValueError("tool replay store did not contain the recorded result")
    return {"schema_version": REPLAY_SCHEMA_VERSION, "status": "replayed" if replayed else "recorded", **entry}
