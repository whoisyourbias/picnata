import io
import json
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from harness import guard, orchestrator


class GuardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "commit", "--allow-empty", "-m", "init"], cwd=self.root, check=True, capture_output=True)
        (self.root / "task.md").write_text("Task", encoding="utf-8")
        approval = patch.object(orchestrator, "check_approval")
        approval.start()
        self.addCleanup(approval.stop)
        self.assertEqual(0, orchestrator.main(["assign", "demo", "task.md", "codex"], cwd=self.root))
        self.worktree = self.root / ".harness" / "worktrees" / "demo"

    def decide(self, path, env=None):
        return guard.decide(str(path), str(self.root), env or {})

    def set_phase(self, phase):
        with closing(sqlite3.connect(self.root / ".harness" / "tasks.sqlite3")) as db, db:
            db.execute("UPDATE tasks SET phase=? WHERE id='demo'", (phase,))

    def test_main_checkout_is_blocked_except_task_specs(self):
        self.assertIsNotNone(self.decide(self.root / "src" / "App.java"))
        self.assertIsNotNone(self.decide("AGENTS.md"))
        self.assertIsNone(self.decide(self.root / "docs" / "tasks" / "login.md"))
        self.assertIsNotNone(self.decide(self.root / "docs" / "tasks" / "nested" / "x.md"))

    def test_harness_state_is_blocked(self):
        self.assertIsNotNone(self.decide(self.root / ".harness" / "tasks.sqlite3"))
        self.assertIsNotNone(self.decide(self.root / ".harness" / "logs" / "demo" / "x.log"))

    def test_worktree_is_editable_only_while_implementing(self):
        target = self.worktree / "src" / "App.java"
        self.assertIn("assigned", self.decide(target))
        self.set_phase("running:implement")
        self.assertIsNone(self.decide(target))
        self.set_phase("running:review")
        self.assertIsNotNone(self.decide(target))

    def test_override_and_outside_paths(self):
        self.assertIsNone(self.decide(self.root / "AGENTS.md", {"HARNESS_GUARD": "off"}))
        with tempfile.TemporaryDirectory() as other:
            self.assertIsNone(self.decide(Path(other) / "notes.md"))

    def run_hook(self, event):
        stderr = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stderr(stderr), \
                patch.dict("os.environ", {}, clear=False) as env:
            env.pop("HARNESS_GUARD", None)
            code = guard.main()
        return code, stderr.getvalue()

    def test_hook_exit_codes(self):
        deny = {"tool_name": "Write", "cwd": str(self.root),
                "tool_input": {"file_path": str(self.root / "main.py")}}
        code, message = self.run_hook(deny)
        self.assertEqual(2, code)
        self.assertIn("하네스 가드", message)
        allow = {"tool_name": "Edit", "cwd": str(self.root),
                 "tool_input": {"file_path": str(self.root / "docs" / "tasks" / "a.md")}}
        self.assertEqual(0, self.run_hook(allow)[0])
        self.assertEqual(0, self.run_hook({"tool_name": "Read", "tool_input": {"file_path": "x"}})[0])

    def test_bash_cannot_approve_or_touch_state(self):
        decide = guard.decide_bash
        self.assertIsNotNone(decide("python -m harness.orchestrator approve demo", {}))
        self.assertIsNotNone(decide("cd x && python harness/orchestrator.py approve demo docs/tasks/demo.md", {}))
        self.assertIsNotNone(decide("sqlite3 .harness/tasks.sqlite3 \"UPDATE tasks SET phase='verified'\"", {}))
        self.assertIsNotNone(decide("python -m harness.orchestrator --timeout 60 approve demo", {}))
        self.assertIsNone(decide("python -m harness.orchestrator status demo", {}))
        self.assertIsNone(decide("python -m harness.orchestrator spec demo \"approve 버튼 추가\" claude", {}))
        self.assertIsNone(decide("git status", {}))
        self.assertIsNone(decide("python -m harness.orchestrator approve demo", {"HARNESS_GUARD": "off"}))

    def test_bash_hook_exit_code(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "python -m harness.orchestrator approve demo"}}
        code, message = self.run_hook(event)
        self.assertEqual(2, code)
        self.assertIn("approve", message)
        self.assertEqual(0, self.run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}})[0])


if __name__ == "__main__":
    unittest.main()
