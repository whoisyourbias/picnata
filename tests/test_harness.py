import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from harness import orchestrator


class AgentLaunchTests(unittest.TestCase):
    def test_desktop_review_uses_standalone_cli_with_read_only_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / "npm" / "codex.cmd"
            launcher.parent.mkdir()
            launcher.touch()
            desktop_env = {
                "APPDATA": directory,
                "CODEX_WINDOWS_REGISTERED_CORE": "1",
                "CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY": "DesktopApp",
            }
            with (
                patch.dict(os.environ, desktop_env),
                patch.object(sys, "platform", "win32"),
                patch.object(orchestrator.shutil, "which", return_value=None),
                patch.object(orchestrator, "run_logged") as run,
            ):
                orchestrator.run_agent("codex", "review", "Review", root, root / "review.log", 60)
                command = run.call_args.args[0]
                self.assertEqual([str(launcher), "-a", "never", "exec", "-s", "read-only", "-"], command)
                child_env = run.call_args.kwargs["env"]
                self.assertNotIn("CODEX_WINDOWS_REGISTERED_CORE", child_env)
                self.assertNotIn("CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY", child_env)
                self.assertEqual("1", os.environ["CODEX_WINDOWS_REGISTERED_CORE"])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.git("init")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-m", "Initial commit")
        (self.root / "task.md").write_text("Add a file.", encoding="utf-8")
        self.state = self.root / ".harness"
        self.worktree = self.state / "worktrees" / "demo"

    def git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd or self.root, check=True,
                       capture_output=True)

    def cli(self, *args):
        return orchestrator.main(list(args), cwd=self.root)

    def implement(self, agent, phase, prompt, cwd, log, timeout):
        self.assertEqual(("codex", "implement", self.worktree), (agent, phase, cwd))
        (cwd / "result.txt").write_text("done", encoding="utf-8")
        self.git("add", "result.txt", cwd=cwd)
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-m", "Implement", cwd=cwd)

    def test_cross_review_and_verification(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertFalse((self.root / "result.txt").exists())
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(0, self.cli("review", "demo"))
            self.assertEqual(("claude", "review"), agent.call_args.args[:2])
            self.assertIn("+done", agent.call_args.args[2])
        self.assertEqual(1, self.cli("verify", "demo", "--", sys.executable, "-c", "raise SystemExit(7)"))
        code = "from pathlib import Path; assert Path('result.txt').read_text() == 'done'"
        self.assertEqual(0, self.cli("verify", "demo", "--", sys.executable, "-c", code))

    def test_verification_rejects_changes_after_review(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))
        with patch.object(orchestrator, "run_agent"):
            self.assertEqual(0, self.cli("review", "demo"))
        (self.worktree / "result.txt").write_text("changed", encoding="utf-8")
        self.assertEqual(1, self.cli("verify", "demo", "--", sys.executable, "-c", "pass"))

    def test_failed_implementation_can_be_retried(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=FileNotFoundError("codex")):
            self.assertEqual(1, self.cli("implement", "demo"))
        self.assertEqual(1, self.cli("review", "demo"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))

    def test_other_tasks_and_duplicate_runs_while_agent_runs(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        results = {}

        def busy(agent, phase, prompt, cwd, log, timeout):
            results["assign"] = self.cli("assign", "other", "task.md", "claude")
            results["status"] = self.cli("status", "other")
            results["same"] = self.cli("implement", "demo")
            self.implement(agent, phase, prompt, cwd, log, timeout)

        with patch.object(orchestrator, "run_agent", side_effect=busy):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertEqual(0, results["assign"])
        self.assertEqual(0, results["status"])
        self.assertEqual(1, results["same"])

    def test_other_task_can_implement_while_agent_runs(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        self.assertEqual(0, self.cli("assign", "other", "task.md", "codex"))
        results = {}

        def busy(agent, phase, prompt, cwd, log, timeout):
            if cwd.name == "demo":
                results["other"] = self.cli("implement", "other")
                with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
                    results["phase"] = db.execute("SELECT phase FROM tasks WHERE id='demo'").fetchone()[0]

        with patch.object(orchestrator, "run_agent", side_effect=busy):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertEqual(0, results["other"])
        self.assertEqual("running:implement", results["phase"])

    def test_failure_restores_previous_phase(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))
        with patch.object(orchestrator, "run_agent", side_effect=OSError("boom")):
            self.assertEqual(1, self.cli("review", "demo"))
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            self.assertEqual(("implemented", "boom"), db.execute(
                "SELECT phase, last_error FROM tasks WHERE id='demo'").fetchone())
