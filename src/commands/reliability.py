"""Operator-facing evaluation surfaces for the reliability control plane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..installer import OmhError
from ..quality.trajectory_evaluation import evaluate_trajectory
from ..quality.recovery_evaluation import evaluate_recovery_cases
from ..quality.recovery_harness import run_process_crash_self_test, run_recovery_self_test
from ..runtime.agent_slos import project_agent_slos
from .common import _print_json


def _read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OmhError(str(exc)) from exc


def cmd_reliability_trajectory(args: argparse.Namespace) -> int:
    raw = _read_json(args.input)
    if not isinstance(raw, list):
        raise OmhError("trajectory input must be a JSON list")
    payload = evaluate_trajectory(raw)
    _print_json(payload)
    return 0


def cmd_reliability_slos(args: argparse.Namespace) -> int:
    raw = _read_json(args.input)
    if not isinstance(raw, list):
        raise OmhError("SLO input must be a JSON list")
    try:
        payload = project_agent_slos(
            raw,
            max_latency_ms=args.max_latency_ms,
            max_cost_usd=args.max_cost_usd,
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_reliability_recovery(args: argparse.Namespace) -> int:
    if args.process_crash:
        payload = run_process_crash_self_test()
        _print_json(payload)
        return 0 if payload.get("status") == "passed" else 1
    if args.self_test:
        payload = run_recovery_self_test()
        _print_json(payload)
        return 0 if payload.get("evaluation", {}).get("status") == "passed" else 1
    raw = _read_json(args.input)
    if not isinstance(raw, list):
        raise OmhError("recovery input must be a JSON list")
    try:
        payload = evaluate_recovery_cases(raw)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _add_reliability_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    reliability = sub.add_parser("reliability", help="Evaluate privacy-safe agent trajectories and reliability SLOs.")
    reliability_sub = reliability.add_subparsers(dest="reliability_command", required=True)

    trajectory = reliability_sub.add_parser("trajectory", help="Evaluate a normalized end-to-end trajectory JSON list.")
    trajectory.add_argument("--input", required=True, help="JSON list of metadata-only trajectory events.")
    trajectory.set_defaults(func=cmd_reliability_trajectory)

    slos = reliability_sub.add_parser("slos", help="Project reliability SLOs from normalized run metadata.")
    slos.add_argument("--input", required=True, help="JSON list of normalized run records.")
    slos.add_argument("--max-latency-ms", type=int, default=60_000)
    slos.add_argument("--max-cost-usd", type=float, default=1.0)
    slos.set_defaults(func=cmd_reliability_slos)

    recovery = reliability_sub.add_parser("recovery", help="Evaluate crash-recovery and replay-safety case records.")
    recovery_mode = recovery.add_mutually_exclusive_group(required=True)
    recovery_mode.add_argument("--input", help="JSON list of normalized recovery case records.")
    recovery_mode.add_argument("--self-test", action="store_true", help="Run isolated local checkpoint/replay scenarios.")
    recovery_mode.add_argument("--process-crash", action="store_true", help="Terminate a worker after checkpointing, then verify restart recovery from disk.")
    recovery.set_defaults(func=cmd_reliability_recovery)
