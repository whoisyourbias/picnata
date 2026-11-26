import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from harness import guard


def run_git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
                   cwd=cwd, check=True, capture_output=True)


class GuardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        run_git(self.root, "init")
        run_git(self.root, "commit", "--allow-empty", "-m", "init")
        self.worktree = self.root / ".harness" / "worktrees" / "demo"
        run_git(self.root, "worktree", "add", "-b", "harness/demo", str(self.worktree))
        self.lock = self.root / ".harness" / "locks" / "demo.json"

    def decide(self, path, env=None):
        return guard.decide(str(path), str(self.root), env or {})

    def set_lock(self, step, pid=None):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text(json.dumps({"pid": os.getpid() if pid is None else pid, "step": step}),
                             encoding="utf-8")

    def test_main_checkout_is_blocked_except_task_specs(self):
        self.assertIsNotNone(self.decide(self.root / "src" / "App.java"))
        self.assertIsNotNone(self.decide("AGENTS.md"))
        self.assertIsNone(self.decide(self.root / "docs" / "tasks" / "login.md"))
        self.assertIsNotNone(self.decide(self.root / "docs" / "tasks" / "nested" / "x.md"))

    def test_harness_state_is_blocked(self):
        self.assertIsNotNone(self.decide(self.root / ".harness" / "locks" / "demo.json"))
        self.assertIsNotNone(self.decide(self.root / ".harness" / "logs" / "demo" / "x.log"))

    def test_worktree_is_editable_only_while_the_lock_names_implement(self):
        target = self.worktree / "src" / "App.java"
        self.assertIsNotNone(self.decide(target))
        self.set_lock("implement")
        self.assertIsNone(self.decide(target))
        self.set_lock("review")
        self.assertIsNotNone(self.decide(target))
        self.set_lock("verify")
        self.assertIsNotNone(self.decide(target))

    def test_dead_pid_does_not_unlock_the_worktree(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.set_lock("implement", pid=child.pid)
        self.assertIsNotNone(self.decide(self.worktree / "src" / "App.java"))
        self.lock.write_text("not json", encoding="utf-8")
        self.assertIsNotNone(self.decide(self.worktree / "src" / "App.java"))

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

    def test_bash_cannot_merge_approve_or_touch_locks(self):
        decide = guard.decide_bash
        for command in ("gh pr merge 12 --squash", "cd x && gh pr merge --auto",
                        "gh -R owner/repo pr merge 3", "gh pr review 4 --approve",
                        "rm .harness/locks/demo.json", "echo '{}' > .harness\\locks\\demo.json"):
            with self.subTest(command):
                self.assertIsNotNone(decide(command, {}))
                self.assertIsNone(decide(command, {"HARNESS_GUARD": "off"}))

    def test_bash_allows_ordinary_commands(self):
        decide = guard.decide_bash
        for command in ("ls", "git status", "gh pr create --base main --head harness/demo",
                        "gh pr view 12", "gh pr review 4 --comment -b ok",
                        "python -m harness.orchestrator status demo",
                        "python -m harness.orchestrator propose demo"):
            with self.subTest(command):
                self.assertIsNone(decide(command, {}))

    def test_bash_hook_exit_code(self):
        event = {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 3"}}
        code, message = self.run_hook(event)
        self.assertEqual(2, code)
        self.assertIn("머지", message)
        self.assertEqual(0, self.run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}})[0])


if __name__ == "__main__":
    unittest.main()
