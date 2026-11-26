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

    def review(self, verdict_text="VERDICT: APPROVE"):
        def run(agent, phase, prompt, cwd, log, timeout):
            log.write_text(f"Findings here.\n{verdict_text}\n", encoding="utf-8")
        return run

    def prepare_reviewed(self, verdict_text):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))
        with patch.object(orchestrator, "run_agent", side_effect=self.review(verdict_text)):
            self.assertEqual(0, self.cli("review", "demo"))

    def test_cross_review_and_verification(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertFalse((self.root / "result.txt").exists())
        with patch.object(orchestrator, "run_agent", side_effect=self.review()) as agent:
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
        with patch.object(orchestrator, "run_agent", side_effect=self.review()):
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

    def test_verify_rejected_when_review_requests_changes(self):
        self.prepare_reviewed("VERDICT: REQUEST_CHANGES")
        self.assertEqual(1, self.cli("verify", "demo", "--", sys.executable, "-c", "pass"))
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            row = db.execute("SELECT phase, review_verdict FROM tasks").fetchone()
        self.assertEqual(("reviewed", "REQUEST_CHANGES"), row)

    def test_reimplement_prompt_includes_previous_findings(self):
        self.prepare_reviewed("VERDICT: REQUEST_CHANGES")
        prompts = []

        def capture(agent, phase, prompt, cwd, log, timeout):
            prompts.append(prompt)
        with patch.object(orchestrator, "run_agent", side_effect=capture):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertIn("Previous review findings", prompts[0])
        self.assertIn("Findings here.", prompts[0])
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            row = db.execute("SELECT reviewed_commit, review_verdict FROM tasks").fetchone()
        self.assertEqual((None, "REQUEST_CHANGES"), row)

    def test_approved_review_is_not_added_to_implement_prompt(self):
        self.prepare_reviewed("VERDICT: APPROVE")
        prompts = []
        with patch.object(orchestrator, "run_agent",
                          side_effect=lambda *a: prompts.append(a[2])):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertNotIn("Previous review findings", prompts[0])

    def test_missing_verdict_line_means_request_changes(self):
        self.prepare_reviewed("No verdict given.")
        self.assertEqual(1, self.cli("verify", "demo", "--", sys.executable, "-c", "pass"))

    def test_parse_verdict(self):
        parse = orchestrator.parse_verdict
        self.assertEqual("APPROVE", parse("ok\nVERDICT: APPROVE\n"))
        self.assertEqual("REQUEST_CHANGES", parse("VERDICT: APPROVE\nVERDICT: REQUEST_CHANGES"))
        self.assertEqual("REQUEST_CHANGES", parse("VERDICT: APPROVE\nVERDICT: MAYBE"))
        self.assertEqual("REQUEST_CHANGES", parse("VERDICT: APPROVE or VERDICT: REQUEST_CHANGES"))
        self.assertEqual("REQUEST_CHANGES", parse("VERDICT: APPROVED"))
        self.assertEqual("REQUEST_CHANGES", parse(""))

    def test_old_schema_database_is_migrated(self):
        self.state.mkdir()
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db, db:
            db.execute("""CREATE TABLE tasks (id TEXT PRIMARY KEY, spec TEXT NOT NULL,
                implementer TEXT NOT NULL, base TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT 'assigned', reviewed_commit TEXT,
                last_log TEXT, last_error TEXT)""")
            db.execute("INSERT INTO tasks (id, spec, implementer, base) VALUES ('old', 's', 'codex', 'b')")
        self.assertEqual(0, self.cli("status", "old"))
        self.assertEqual(0, self.cli("status", "old"))
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            row = db.execute("SELECT review_verdict, review_notes FROM tasks").fetchone()
        self.assertTrue({"review_verdict", "review_notes"} <= columns)
        self.assertEqual((None, None), row)
