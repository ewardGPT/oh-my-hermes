from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.paths import resolve_paths
from omh.runtime.artifacts import create_run
from omh.runtime.checkpoints import (
    CheckpointConflict,
    read_checkpoint,
    record_tool_result,
    resume_checkpoint,
    save_checkpoint,
)


class RuntimeCheckpointTests(unittest.TestCase):
    def _run_dir(self, tmp: str) -> tuple[object, Path, str]:
        paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
        run = create_run(paths, {"skill": "plan", "harness": "coding-handling", "status": "started"})
        run_dir = paths.runtime_runs_dir / run["run_id"]
        return paths, run_dir, str(run["run_id"])

    def test_checkpoint_is_atomic_monotonic_and_resumable(self) -> None:
        with TemporaryDirectory() as tmp:
            _paths, run_dir, _run_id = self._run_dir(tmp)
            first = save_checkpoint(
                run_dir,
                phase="route",
                state={"cursor": "route"},
                next_action="continue_to_tool",
                idempotency_key="checkpoint-1",
            )
            retry = save_checkpoint(
                run_dir,
                phase="route",
                state={"cursor": "route"},
                next_action="continue_to_tool",
                idempotency_key="checkpoint-1",
            )
            self.assertEqual(first, retry)
            second = save_checkpoint(
                run_dir,
                phase="tool",
                state={"cursor": "tool", "tool_id": "search-1"},
                next_action="resume_tool",
                idempotency_key="checkpoint-2",
            )
            self.assertEqual(second["sequence"], 2)
            self.assertEqual(read_checkpoint(run_dir)["phase"], "tool")
            resumed = resume_checkpoint(run_dir)
            self.assertEqual(resumed["status"], "resumable")
            self.assertEqual(resumed["checkpoint"]["next_action"], "resume_tool")
            with self.assertRaises(CheckpointConflict):
                save_checkpoint(
                    run_dir,
                    phase="tool",
                    state={"cursor": "different"},
                    next_action="resume_tool",
                    idempotency_key="checkpoint-2",
                )

            completed = save_checkpoint(
                run_dir,
                phase="outcome",
                state={"cursor": "done"},
                next_action="inspect_run",
                idempotency_key="checkpoint-3",
                status="completed",
            )
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(resume_checkpoint(run_dir)["status"], "not_resumable")

    def test_tool_result_replay_returns_original_result_and_rejects_key_reuse(self) -> None:
        with TemporaryDirectory() as tmp:
            _paths, run_dir, _run_id = self._run_dir(tmp)
            recorded = record_tool_result(
                run_dir,
                idempotency_key="tool-call-1",
                tool_name="search",
                arguments_digest="args-digest",
                result={"items": ["a"], "status": "ok"},
            )
            replayed = record_tool_result(
                run_dir,
                idempotency_key="tool-call-1",
                tool_name="search",
                arguments_digest="args-digest",
                result={"items": ["different"], "status": "ok"},
            )
            self.assertEqual(recorded["status"], "recorded")
            self.assertEqual(replayed["status"], "replayed")
            self.assertEqual(replayed["result"], recorded["result"])
            with self.assertRaises(CheckpointConflict):
                record_tool_result(
                    run_dir,
                    idempotency_key="tool-call-1",
                    tool_name="search",
                    arguments_digest="different-args",
                    result={"status": "unsafe"},
                )

    def test_resume_reports_corrupt_checkpoint_as_unresumable(self) -> None:
        with TemporaryDirectory() as tmp:
            _paths, run_dir, _run_id = self._run_dir(tmp)
            (run_dir / "checkpoint.json").write_text('{"checkpoint":', encoding="utf-8")
            resumed = resume_checkpoint(run_dir)
            self.assertEqual(resumed["status"], "checkpoint_corrupt")
            self.assertEqual(resumed["next_action"], "inspect_run")

    def test_checkpoint_and_resume_cli_expose_recovery_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(base + ["runtime", "record", "--skill", "plan", "--harness", "coding-handling"])
            self.assertEqual((status, stderr), (0, ""))
            run_id = json.loads(stdout)["run"]["run_id"]
            status, stdout, stderr = run_cli(
                base
                + [
                    "runtime",
                    "checkpoint",
                    "--run",
                    run_id,
                    "--phase",
                    "tool",
                    "--next-action",
                    "resume_tool",
                    "--state-json",
                    '{"cursor":"tool"}',
                    "--idempotency-key",
                    "checkpoint-cli-1",
                ]
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["checkpoint"]["phase"], "tool")
            status, stdout, stderr = run_cli(base + ["runtime", "resume", "--run", run_id])
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["status"], "resumable")
            self.assertEqual(payload["checkpoint"]["next_action"], "resume_tool")
            tool_args = base + [
                "runtime",
                "tool-result",
                "--run",
                run_id,
                "--tool",
                "search",
                "--arguments-digest",
                "args-1",
                "--idempotency-key",
                "tool-cli-1",
                "--result-json",
                '{"items":["a"]}',
            ]
            status, stdout, stderr = run_cli(tool_args)
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["tool_result"]["status"], "recorded")
            status, stdout, stderr = run_cli(tool_args[:-1] + ['{"items":["different"]}'])
            self.assertEqual((status, stderr), (0, ""))
            replay = json.loads(stdout)["tool_result"]
            self.assertEqual(replay["status"], "replayed")
            self.assertEqual(replay["result"], {"items": ["a"]})


if __name__ == "__main__":
    unittest.main()
