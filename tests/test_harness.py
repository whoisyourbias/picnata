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
        # The approval gate has its own tests; workflow tests start from an approved specification.
        approval = patch.object(orchestrator, "check_approval")
        approval.start()
        self.addCleanup(approval.stop)

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

    def implement_uncommitted(self, agent, phase, prompt, cwd, log, timeout):
        (cwd / "result.txt").write_text("done", encoding="utf-8")

    def test_harness_commits_uncommitted_agent_changes(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement_uncommitted):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertEqual("", orchestrator.git(self.worktree, "status", "--porcelain", "--untracked-files=all"))
        self.assertEqual("harness: implement demo", orchestrator.git(self.worktree, "log", "-1", "--format=%s"))
        self.assertEqual("harness", orchestrator.git(self.worktree, "log", "-1", "--format=%an"))
        with patch.object(orchestrator, "run_agent"):
            self.assertEqual(0, self.cli("review", "demo"))

    def test_no_extra_commit_when_agent_already_committed(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement):
            self.assertEqual(0, self.cli("implement", "demo"))
        self.assertEqual("Implement", orchestrator.git(self.worktree, "log", "-1", "--format=%s"))
        self.assertEqual("2", orchestrator.git(self.worktree, "rev-list", "--count", "HEAD"))

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

    def implement_tool(self, agent, phase, prompt, cwd, log, timeout):
        (cwd / "tools").mkdir()
        script = cwd / "tools" / "check.cmd"
        if sys.platform == "win32":
            script.write_text("@echo ok\r\n", encoding="utf-8")
        else:
            script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
            script.chmod(0o755)

    def test_verify_runs_worktree_relative_executable(self):
        self.assertEqual(0, self.cli("assign", "demo", "task.md", "codex"))
        with patch.object(orchestrator, "run_agent", side_effect=self.implement_tool):
            self.assertEqual(0, self.cli("implement", "demo"))
        with patch.object(orchestrator, "run_agent", side_effect=self.review()):
            self.assertEqual(0, self.cli("review", "demo"))
        self.assertFalse((self.root / "tools").exists())
        self.assertEqual(0, self.cli("verify", "demo", "--", "tools/check.cmd"))

    def test_verify_missing_relative_executable_fails(self):
        self.prepare_reviewed("VERDICT: APPROVE")
        self.assertEqual(1, self.cli("verify", "demo", "--", "tools/missing.cmd"))
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            error = db.execute("SELECT last_error FROM tasks WHERE id='demo'").fetchone()[0]
        self.assertIn("Executable not found", error)

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

    def run_agent_script(self, verdicts):
        calls, answers = [], iter(verdicts)

        def agent(name, phase, prompt, cwd, log, timeout):
            calls.append((name, phase))
            if phase == "implement":
                (cwd / "result.txt").write_text(f"v{len(calls)}", encoding="utf-8")
            else:
                log.write_text(f"Finding.\n{next(answers)}\n", encoding="utf-8")
        return calls, agent

    def test_run_reworks_until_review_approves_then_verifies(self):
        calls, agent = self.run_agent_script(["VERDICT: REQUEST_CHANGES", "VERDICT: APPROVE"])
        with patch.object(orchestrator, "run_agent", side_effect=agent):
            code = self.cli("run", "demo", "task.md", "codex", "--", sys.executable, "-c", "pass")
        self.assertEqual(0, code)
        self.assertEqual([("codex", "implement"), ("claude", "review")] * 2, calls)
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            self.assertEqual("verified", db.execute("SELECT phase FROM tasks").fetchone()[0])
        with patch.object(orchestrator, "run_agent") as agent_again:
            self.assertEqual(0, self.cli("run", "demo", "task.md", "codex", "--", sys.executable, "-c", "pass"))
        agent_again.assert_not_called()

    def test_run_stops_for_human_after_max_rounds(self):
        calls, agent = self.run_agent_script(["VERDICT: REQUEST_CHANGES"] * 2)
        with patch.object(orchestrator, "run_agent", side_effect=agent):
            code = self.cli("--timeout", "60", "run", "demo", "task.md", "codex", "--max-rounds", "2",
                            "--", sys.executable, "-c", "pass")
        self.assertEqual(1, code)
        self.assertEqual(2, [phase for _, phase in calls].count("implement"))
        with closing(sqlite3.connect(self.state / "tasks.sqlite3")) as db:
            self.assertEqual(("reviewed", "REQUEST_CHANGES"),
                             tuple(db.execute("SELECT phase, review_verdict FROM tasks").fetchone()))

    def test_run_requires_verification_command(self):
        with self.assertRaises(SystemExit):
            self.cli("run", "demo", "task.md", "codex")

    def spec_agent(self, output, seen=None, side=None):
        def agent(name, phase, prompt, cwd, log, timeout):
            if seen is not None:
                seen.update(name=name, phase=phase, prompt=prompt, cwd=cwd)
            if side:
                side(cwd)
            log.write_text(output, encoding="utf-8")
            return log
        return agent

    def test_spec_runs_agent_with_template_and_request(self):
        seen = {}
        output = "명세입니다.\n# Login\n\n## 가정\n- 이메일 로그인\n\n## 열린 질문\n없음\n"
        with patch.object(orchestrator, "run_agent", side_effect=self.spec_agent(output, seen)):
            self.assertEqual(0, self.cli("spec", "login", "로그인 기능 {request} 추가", "claude"))
        self.assertEqual(("claude", "spec", self.root.resolve()), (seen["name"], seen["phase"], seen["cwd"].resolve()))
        self.assertIn("로그인 기능 {request} 추가", seen["prompt"])
        self.assertIn("docs/tasks/login.md", seen["prompt"])
        self.assertNotIn("{task_path}", seen["prompt"])
        written = (self.root / "docs" / "tasks" / "login.md").read_text(encoding="utf-8")
        self.assertTrue(written.startswith("# Login\n"))
        with patch.object(orchestrator, "run_agent") as again:
            self.assertEqual(1, self.cli("spec", "login", "다시", "claude"))
        again.assert_not_called()

    def test_spec_rejects_changes_outside_the_specification(self):
        def side(cwd):
            (cwd / "extra.py").write_text("print()", encoding="utf-8")

        with patch.object(orchestrator, "run_agent", side_effect=self.spec_agent("# Login\n", side=side)):
            self.assertEqual(1, self.cli("spec", "login", "로그인", "codex"))
        self.assertFalse((self.root / "docs" / "tasks" / "login.md").exists())

    def test_spec_rejects_agent_writing_the_specification_itself(self):
        def side(cwd):
            (cwd / "docs" / "tasks" / "login.md").write_text("# Login\n", encoding="utf-8")

        with patch.object(orchestrator, "run_agent", side_effect=self.spec_agent("# Login\n", side=side)):
            self.assertEqual(1, self.cli("spec", "login", "로그인", "codex"))

    def test_spec_fails_when_agent_outputs_no_specification(self):
        with patch.object(orchestrator, "run_agent", side_effect=self.spec_agent("명세를 못 썼습니다.")):
            self.assertEqual(1, self.cli("spec", "login", "로그인", "codex"))
        self.assertFalse((self.root / "docs" / "tasks" / "login.md").exists())

    def test_extract_spec(self):
        self.assertEqual("# A\nbody\n", orchestrator.extract_spec("```markdown\n# A\nbody\n```"))
        self.assertEqual("# A\n", orchestrator.extract_spec("요약\n# A"))
        self.assertIsNone(orchestrator.extract_spec("## only a section"))


class SpecLaunchTests(unittest.TestCase):
    def launch(self, agent):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(orchestrator.shutil, "which", return_value=agent),
                patch.object(orchestrator, "run_logged") as run,
            ):
                final = orchestrator.run_agent(agent, "spec", "Spec", root, root / "spec.log", 60)
            return run.call_args.args[0], final, root

    def test_codex_spec_is_read_only_and_saves_final_message(self):
        command, final, root = self.launch("codex")
        self.assertEqual(["codex", "-a", "never", "exec", "-s", "read-only", "-o", str(final), "-"], command)
        self.assertEqual(root / "spec-final.md", final)

    def test_claude_spec_cannot_edit_or_run_commands(self):
        command, final, root = self.launch("claude")
        self.assertEqual(["claude", "-p", "--permission-mode", "default",
                          "--disallowedTools", "Edit,Write,MultiEdit,NotebookEdit,Bash"], command)
        self.assertEqual(root / "spec.log", final)


class ImplementPermissionTests(unittest.TestCase):
    def launch(self, agent, phase):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(orchestrator.shutil, "which", return_value=agent),
                patch.object(orchestrator, "run_logged") as run,
            ):
                orchestrator.run_agent(agent, phase, "Go", root, root / "x.log", 60)
            return run.call_args.args[0]

    def test_claude_implement_allows_gradle(self):
        command = self.launch("claude", "implement")
        allowed = command[command.index("--allowedTools") + 1].split(",")
        for tool in ["Bash(python -m unittest:*)", "Bash(python3 -m unittest:*)", "Bash(gradle:*)",
                     "Bash(./gradlew:*)", "Bash(gradlew:*)", "Bash(gradlew.bat:*)",
                     "Bash(backend/gradlew:*)", "Bash(backend/gradlew.bat:*)",
                     "Bash(./backend/gradlew:*)"]:
            self.assertIn(tool, allowed)

    def test_claude_review_has_no_allowed_tools(self):
        command = self.launch("claude", "review")
        self.assertNotIn("--allowedTools", command)
        self.assertEqual("plan", command[command.index("--permission-mode") + 1])

    def test_codex_implement_unchanged(self):
        self.assertEqual(["codex", "-a", "never", "exec", "-s", "workspace-write", "-"],
                         self.launch("codex", "implement"))


class RelativeExecutableTests(unittest.TestCase):
    def test_resolves_relative_to_cwd_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir()
            if sys.platform == "win32":
                script = tools / "check.cmd"
                script.write_text("@echo ok\r\n", encoding="utf-8")
                name = "tools/check.cmd"
            else:
                script = tools / "check.sh"
                script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
                script.chmod(0o755)
                name = "tools/check.sh"
            log = root / "out.log"
            orchestrator.run_logged([name], root, log, 60)
            self.assertIn("ok", log.read_text())
            with self.assertRaisesRegex(FileNotFoundError, "Executable not found"):
                orchestrator.run_logged(["tools/missing.sh"], root, log, 60)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "commit", "--allow-empty", "-m", "init"], cwd=self.root, check=True, capture_output=True)
        self.spec = self.root / "docs" / "tasks" / "demo.md"
        self.spec.parent.mkdir(parents=True)
        self.spec.write_text("# Demo\n\n## 가정\n- 하나\n\n## 열린 질문\n없음\n", encoding="utf-8")

    def cli(self, *args):
        return orchestrator.main(list(args), cwd=self.root)

    def approve(self, answer="demo", tty=True, *extra):
        with patch.object(sys.stdin, "isatty", return_value=tty), \
                patch("builtins.input", return_value=answer) as asked:
            return self.cli("approve", "demo", *extra), asked

    def assign(self):
        return self.cli("assign", "demo", "docs/tasks/demo.md", "codex")

    def test_assign_requires_approval(self):
        self.assertEqual(1, self.assign())
        self.assertEqual(0, self.approve()[0])
        self.assertEqual(0, self.assign())

    def test_approval_needs_a_terminal(self):
        code, asked = self.approve(tty=False)
        self.assertEqual(1, code)
        asked.assert_not_called()
        self.assertEqual(1, self.assign())

    def test_approval_needs_the_task_id_typed(self):
        self.assertEqual(1, self.approve(answer="y")[0])
        self.assertEqual(1, self.assign())

    def test_changed_specification_needs_new_approval(self):
        self.assertEqual(0, self.approve()[0])
        self.spec.write_text("# Demo\n\n범위를 넓혔다.\n", encoding="utf-8")
        self.assertEqual(1, self.assign())
        self.assertEqual(0, self.approve()[0])
        self.assertEqual(0, self.assign())

    def test_run_stops_without_approval(self):
        with patch.object(orchestrator, "run_agent") as agent:
            code = self.cli("run", "demo", "docs/tasks/demo.md", "codex", "--", sys.executable, "-c", "pass")
        self.assertEqual(1, code)
        agent.assert_not_called()

    def test_approve_explicit_path_and_assigned_task(self):
        other = self.root / "other.md"
        other.write_text("# Other\n", encoding="utf-8")
        self.assertEqual(0, self.approve("demo", True, "other.md")[0])
        self.assertEqual(0, self.cli("assign", "demo", "other.md", "claude"))
        self.assertEqual(1, self.approve()[0])
