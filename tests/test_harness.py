import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import orchestrator

REPO = Path(__file__).resolve().parents[1]
IDENT = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]

SPEC = """# 데모 작업

## 목표
파일을 추가한다.

## 검증 명령
```
python -c "from pathlib import Path; assert Path('result.txt').exists()"
```

## 가정
- 없음

## 열린 질문
없음
"""

FAKE_GH = """import json, os, sys
state = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]
body = sys.stdin.buffer.read().decode("utf-8") if args[:2] == ["pr", "create"] else None
if body is not None:
    with open(os.path.join(state, "body.md"), "w", encoding="utf-8") as out:
        out.write(body)
if args[:1] == ["auth"]:
    sys.exit(0)
prs = os.path.join(state, "prs.json")
if args[:2] == ["pr", "list"]:
    print(open(prs).read() if os.path.exists(prs) else "[]")
elif args[:2] == ["pr", "create"]:
    with open(os.path.join(state, "calls.log"), "a", encoding="utf-8") as log:
        log.write(" ".join(args) + "\\n")
    with open(prs, "w") as out:
        json.dump([{"url": "https://example.invalid/pull/1"}], out)
    print("https://example.invalid/pull/1")
"""


def run_git(cwd, *args, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8")
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


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
                self.assertEqual([str(launcher), "-a", "never", "exec", "-s", "read-only",
                                  "-o", str(root / "review-final.md"), "-"], command)
                child_env = run.call_args.kwargs["env"]
                self.assertNotIn("CODEX_WINDOWS_REGISTERED_CORE", child_env)
                self.assertNotIn("CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY", child_env)
                self.assertEqual("1", os.environ["CODEX_WINDOWS_REGISTERED_CORE"])


class ClaudeFinalResponseTests(unittest.TestCase):
    def test_claude_stdout_is_captured_apart_from_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, final = root / "implement.log", root / "implement-final.md"
            with patch.object(orchestrator, "run_logged") as run:
                result = orchestrator.run_agent("claude", "implement", "Go", root, log, 60)
            self.assertEqual(final, result)
            self.assertEqual(final, run.call_args.kwargs["stdout_path"])

    def test_run_logged_keeps_stderr_out_of_the_final_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = "import sys; print('FINAL'); print('DIAGNOSTIC', file=sys.stderr)"
            orchestrator.run_logged([sys.executable, "-c", script], root, root / "a.log", 60,
                                    stdout_path=root / "a-final.md")
            self.assertEqual("FINAL", (root / "a-final.md").read_text(encoding="utf-8").strip())
            self.assertNotIn("DIAGNOSTIC", (root / "a-final.md").read_text(encoding="utf-8"))
            self.assertIn("DIAGNOSTIC", (root / "a.log").read_text(encoding="utf-8"))


class SpecParsingTests(unittest.TestCase):
    def command(self, section):
        return orchestrator.verify_command(f"# T\n\n## 검증 명령\n{section}\n\n## 가정\n- x\n")[1]

    def test_command_from_code_block(self):
        self.assertEqual(["python", "-m", "unittest"], self.command("```\npython -m unittest\n```"))

    def test_command_from_first_body_line_without_block(self):
        self.assertEqual(["python", "-c", "pass"], self.command("`python -c pass`\n두 번째 줄"))

    def test_multiline_code_block_is_one_command(self):
        self.assertEqual(["python", "-m", "unittest", "-v", "x"],
                         self.command("```\npython -m unittest \\\n  -v\nx\n```"))

    def test_empty_command_is_an_error(self):
        with self.assertRaises(ValueError):
            self.command("```\n```")
        with self.assertRaises(ValueError):
            self.command("")
        with self.assertRaises(ValueError):
            orchestrator.verify_command("# T\n\n## 목표\nx\n")


class ParseVerdictTests(unittest.TestCase):
    def parse(self, text):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            verdict = orchestrator.parse_verdict(text)
        return verdict, stderr.getvalue()

    def test_blocking_count_decides(self):
        cases = [
            ("좋습니다.\nBLOCKING: 0\nVERDICT: APPROVE", "APPROVE", False),
            ("좋습니다.\nBLOCKING: 0\nVERDICT: REQUEST_CHANGES", "APPROVE", True),
            ("문제\nBLOCKING: 2\nVERDICT: APPROVE", "REQUEST_CHANGES", True),
            ("문제\nBLOCKING: 1\nVERDICT: REQUEST_CHANGES\n", "REQUEST_CHANGES", False),
            ("좋습니다.\nVERDICT: APPROVE", "MISSING", False),
            ("좋습니다.\nBLOCKING: 0\nVERDICT: APPROVE\n\n\n", "APPROVE", False),
            ("좋습니다.\r\nBLOCKING: 0\r\nVERDICT: APPROVE\r\n  \r\n", "APPROVE", False),
            ("좋습니다.\n    BLOCKING: 0\n    VERDICT: APPROVE", "MISSING", False),
            ("좋습니다.\nBLOCKING: 0  \nVERDICT: APPROVE  ", "MISSING", False),
            ("BLOCKING: 0\n\nVERDICT: APPROVE", "MISSING", False),
            ("BLOCKING: 0\n   \nVERDICT: APPROVE\n", "MISSING", False),
            ("BLOCKING: -1\nVERDICT: APPROVE", "MISSING", False),
            ("BLOCKING: x\nVERDICT: APPROVE", "MISSING", False),
            ("BLOCKING: 0\nVERDICT: APPROVE\n그러나 버그가 있습니다.", "MISSING", False),
            ("BLOCKING: 0\nVERDICT: APPROVE please", "MISSING", False),
            ("VERDICT: APPROVE\nBLOCKING: 0", "MISSING", False),
            ("", "MISSING", False),
        ]
        for text, expected, warns in cases:
            with self.subTest(text=text):
                verdict, stderr = self.parse(text)
                self.assertEqual(expected, verdict)
                if warns:
                    self.assertIn("리뷰 판정과 BLOCKING 수가 어긋나 BLOCKING 수를 따릅니다", stderr)
                else:
                    self.assertEqual("", stderr)

    def test_follow_ups_section(self):
        follow = orchestrator.review_follow_ups
        review = "## Blocking\nNone\n\n## Follow-ups\n- 이름을 바꾸자.\n- 문서를 다듬자.\n\nBLOCKING: 0\nVERDICT: APPROVE"
        self.assertEqual("- 이름을 바꾸자.\n- 문서를 다듬자.", follow(review))
        self.assertEqual("", follow("## Blocking\nNone\n\n## Follow-ups\nNone\n\nBLOCKING: 0\nVERDICT: APPROVE"))
        self.assertEqual("", follow("좋습니다.\nBLOCKING: 0\nVERDICT: APPROVE"))
        self.assertEqual("- a", follow("## Follow-ups\n- a\n## Other\n- b"))
        self.assertEqual("### Documentation\n- Add an example.",
                         follow("## Follow-ups\n### Documentation\n- Add an example.\n\nBLOCKING: 0\nVERDICT: APPROVE"))
        self.assertEqual("### A\n- a\n#### A1\n- a1\n### B\n- b",
                         follow("# Review\n## Blocking\nNone\n## Follow-ups\n### A\n- a\n#### A1\n- a1\n"
                                "### B\n- b\n# Next\n- c"))
        self.assertEqual("- a", follow("## Follow-ups\n- a\n# Top\n- b"))

class PromptTests(unittest.TestCase):
    def test_review_prompt_states_severity_and_format(self):
        text = orchestrator.REVIEW_INSTRUCTIONS
        for phrase in ("Blocking:", "Follow-up:", "If you are unsure, classify the finding as Follow-up",
                       "`## Blocking`", "`## Follow-ups`", "`None`",
                       "BLOCKING: <number of blocking findings>\nVERDICT: <APPROVE|REQUEST_CHANGES>",
                       "reproduction scenario", "bypasses or weakens", "breaks existing tests",
                       "concurrent runs or timing races"):
            self.assertIn(phrase, text)


class LockTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        self.lock = self.state / "locks" / "demo.json"

    def test_live_pid_is_refused(self):
        self.lock.parent.mkdir()
        self.lock.write_text(json.dumps({"pid": os.getpid(), "step": "implement"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "이미 실행 중"):
            with orchestrator.step_lock(self.state, "demo", "review"):
                pass
        self.assertTrue(self.lock.exists())

    def test_dead_pid_is_reclaimed_and_lock_removed_afterwards(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.lock.parent.mkdir()
        self.lock.write_text(json.dumps({"pid": child.pid, "step": "implement"}), encoding="utf-8")
        with orchestrator.step_lock(self.state, "demo", "verify"):
            info = json.loads(self.lock.read_text(encoding="utf-8"))
            self.assertEqual((os.getpid(), "verify"), (info["pid"], info["step"]))
            self.assertIn("started", info)
        self.assertFalse(self.lock.exists())

    def test_concurrent_reclaim_admits_only_one(self):
        import threading
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.lock.parent.mkdir()
        self.lock.write_text(json.dumps({"pid": child.pid, "step": "implement"}), encoding="utf-8")
        inside, refused, barrier = [], [], threading.Barrier(4)

        def worker():
            barrier.wait()
            try:
                with orchestrator.step_lock(self.state, "demo", "implement"):
                    inside.append(1)
                    time.sleep(0.3)
            except ValueError:
                refused.append(1)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, len(inside))
        self.assertEqual(3, len(refused))

    def test_creation_waits_for_the_reclaim_mutex(self):
        """A runner must not touch the lock while another holder has the OS mutex, however long it takes."""
        import threading
        self.lock.parent.mkdir()
        mutex = self.lock.with_suffix(".reclaim")
        entered = []

        def worker():
            with orchestrator.step_lock(self.state, "demo", "implement"):
                entered.append(time.time())

        with orchestrator.os_mutex(mutex):
            # Even a mutex file that looks ancient must not be taken over from a live holder.
            os.utime(mutex, (0, 0))
            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.4)
            self.assertEqual([], entered)
            released = time.time()
        thread.join(10)
        self.assertEqual(1, len(entered))
        self.assertGreaterEqual(entered[0], released)
        self.assertFalse(self.lock.exists())

    def test_lock_is_removed_on_exception(self):
        with self.assertRaises(RuntimeError):
            with orchestrator.step_lock(self.state, "demo", "review"):
                raise RuntimeError
        self.assertFalse(self.lock.exists())


class CliTests(unittest.TestCase):
    def test_removed_subcommands_are_rejected(self):
        for name in ("assign", "implement", "review", "verify", "approve"):
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    orchestrator.main([name, "demo"])
                self.assertEqual(2, raised.exception.code)
                self.assertIn("invalid choice", stderr.getvalue())

    def test_no_sqlite_in_harness_code_or_docs(self):
        for path in (REPO / "harness").glob("*.py"):
            self.assertNotIn("sqlite3", path.read_text(encoding="utf-8"), path.name)
        for name in ("AGENTS.md", "docs/agent-collaboration.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertNotIn("sqlite", text.lower(), name)
            # The review verdict APPROVE stays; the removed approve subcommand must not.
            self.assertNotIn("approve", text, name)


class GitFlowTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name).resolve()
        self.origin = base / "origin.git"
        self.root = base / "main"
        self.gh_state = base / "gh"
        self.gh_state.mkdir()
        run_git(base, "init", "--bare", str(self.origin))
        run_git(base, "init", str(self.root))
        run_git(self.root, "symbolic-ref", "HEAD", "refs/heads/main")
        run_git(self.root, *IDENT, "commit", "--allow-empty", "-m", "Initial commit")
        run_git(self.root, "remote", "add", "origin", str(self.origin))
        run_git(self.root, "push", "origin", "main")
        run_git(self.origin, "symbolic-ref", "HEAD", "refs/heads/main")
        self.state = self.root / ".harness"
        self.worktree = self.state / "worktrees" / "demo"
        self.spec_path = self.root / "docs" / "tasks" / "demo.md"
        self.set_spec(SPEC)
        self.install_fake_gh(base)
        self.calls = []

    def install_fake_gh(self, base):
        bin_dir = base / "bin"
        bin_dir.mkdir()
        script = bin_dir / "fake_gh.py"
        script.write_text(FAKE_GH, encoding="utf-8")
        if os.name == "nt":
            (bin_dir / "gh.cmd").write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        else:
            launcher = bin_dir / "gh"
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
            launcher.chmod(0o755)
        env = patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                                      "FAKE_GH_STATE": str(self.gh_state)})
        env.start()
        self.addCleanup(env.stop)

    def set_spec(self, text):
        self.spec_path.parent.mkdir(parents=True, exist_ok=True)
        self.spec_path.write_text(text, encoding="utf-8")

    def merge_spec(self):
        """Simulate the specification PR being merged into main."""
        run_git(self.root, "add", "docs/tasks/demo.md")
        run_git(self.root, *IDENT, "commit", "-m", "spec")
        run_git(self.root, "push", "origin", "main")

    def cli(self, *args):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = orchestrator.main(list(args), cwd=self.root)
        self.stderr = stderr.getvalue()
        return code

    def branch_commits(self):
        return list(reversed(orchestrator.read_commits(self.worktree)))

    def steps(self):
        return [(c["trailers"]["Harness-Step"], c["trailers"].get("Harness-Verdict")
                 or c["trailers"].get("Harness-Result")) for c in self.branch_commits()]

    def agent(self, verdicts=("APPROVE",), crash_review=False):
        """A fake agent: implement writes result.txt, review answers from the verdict list.

        A verdict is APPROVE, REQUEST_CHANGES (mapped to BLOCKING 0 / 1) or a full review text."""
        reviews = iter(verdicts)
        canned = {"APPROVE": "Fix the thing.\nBLOCKING: 0\nVERDICT: APPROVE\n",
                  "REQUEST_CHANGES": "Fix the thing.\nBLOCKING: 1\nVERDICT: REQUEST_CHANGES\n"}

        def run(agent, phase, prompt, cwd, log, timeout):
            self.calls.append((agent, phase, prompt))
            if phase == "implement":
                (Path(cwd) / "result.txt").write_text(f"round {len(self.calls)}", encoding="utf-8")
                log.write_text("RAW LOG NOISE\n", encoding="utf-8")
                final = log.with_name(log.stem + "-final.md")
                final.write_text("구현을 마쳤습니다.", encoding="utf-8")
                return final
            if crash_review:
                raise ValueError("agent crashed")
            review = next(reviews)
            log.write_text(canned.get(review, review), encoding="utf-8")
        return run


class ProposeTests(GitFlowTestCase):
    def test_open_questions_block_propose(self):
        self.set_spec(SPEC.replace("## 열린 질문\n없음", "## 열린 질문\n- 무엇을?"))
        self.assertEqual(1, self.cli("propose", "demo"))
        self.assertIn("열린 질문이 남아 있습니다. 사용자와 정리한 뒤 다시 propose 하세요.", self.stderr)
        self.assertEqual("", run_git(self.origin, "branch", "--list", "spec/demo"))

    def test_missing_or_empty_spec_is_rejected(self):
        self.spec_path.write_text("  \n", encoding="utf-8")
        self.assertEqual(1, self.cli("propose", "demo"))
        self.spec_path.unlink()
        self.assertEqual(1, self.cli("propose", "demo"))

    def test_propose_pushes_one_file_on_top_of_origin_main(self):
        before = (run_git(self.root, "rev-parse", "HEAD"), run_git(self.root, "status", "--porcelain"),
                  run_git(self.root, "ls-files"), run_git(self.root, "symbolic-ref", "HEAD"),
                  self.spec_path.read_text(encoding="utf-8"))
        self.assertEqual(0, self.cli("propose", "demo"), self.stderr)
        after = (run_git(self.root, "rev-parse", "HEAD"), run_git(self.root, "status", "--porcelain"),
                 run_git(self.root, "ls-files"), run_git(self.root, "symbolic-ref", "HEAD"),
                 self.spec_path.read_text(encoding="utf-8"))
        self.assertEqual(before, after)
        main = run_git(self.origin, "rev-parse", "main")
        self.assertEqual(main, run_git(self.origin, "rev-parse", "spec/demo^"))
        self.assertEqual("docs/tasks/demo.md", run_git(self.origin, "diff", "--name-only", main, "spec/demo"))
        message = run_git(self.origin, "log", "-1", "--format=%B", "spec/demo")
        self.assertTrue(message.startswith("spec(demo): 데모 작업\n\nHarness-Task: demo"))
        self.assertEqual("harness", run_git(self.origin, "log", "-1", "--format=%an", "spec/demo"))
        self.assertIn("pr create --base main --head spec/demo --title spec: 데모 작업",
                      (self.gh_state / "calls.log").read_text(encoding="utf-8"))

    def test_existing_pr_is_not_duplicated(self):
        self.assertEqual(0, self.cli("propose", "demo"), self.stderr)
        self.assertEqual(0, self.cli("propose", "demo"), self.stderr)
        calls = (self.gh_state / "calls.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, len(calls))

    def test_already_approved_spec_is_rejected(self):
        self.merge_spec()
        self.assertEqual(1, self.cli("propose", "demo"))
        self.assertIn("이미", self.stderr)

    def test_without_gh_the_branch_is_still_pushed(self):
        with patch.object(orchestrator, "gh_available", return_value=None):
            self.assertEqual(1, self.cli("propose", "demo"))
        self.assertIn("gh를 설치하고 gh auth login 하세요", self.stderr)
        self.assertIn("spec/demo", run_git(self.origin, "branch", "--list", "spec/demo"))


class RunTests(GitFlowTestCase):
    def run_cli(self, *extra):
        return self.cli("run", "demo", "codex", *extra)

    def test_unapproved_spec_exits_with_3(self):
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(3, self.run_cli())
            agent.assert_not_called()
        self.assertIn("명세 PR(spec/demo)이 아직 머지되지 않았습니다.", self.stderr)
        self.assertFalse(self.worktree.exists())

    def test_wait_times_out_with_3(self):
        with patch.object(orchestrator, "WAIT_INTERVAL", 0.05):
            self.assertEqual(3, self.run_cli("--wait", "0.1"))

    def test_full_flow_commits_trailers_and_pushes(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent",
                          side_effect=self.agent(("REQUEST_CHANGES", "APPROVE"))):
            self.assertEqual(0, self.run_cli(), self.stderr)
        self.assertEqual([("implement", None), ("review", "REQUEST_CHANGES"), ("implement", None),
                          ("review", "APPROVE"), ("verify", "pass")], self.steps())
        commits = self.branch_commits()
        rounds = [c["trailers"].get("Harness-Round") for c in commits]
        self.assertEqual(["1", None, "2", None, None], rounds)
        self.assertEqual(commits[0]["sha"], commits[1]["trailers"]["Harness-Reviewed"])
        self.assertEqual(commits[2]["sha"], commits[3]["trailers"]["Harness-Reviewed"])
        self.assertEqual(commits[2]["sha"], commits[4]["trailers"]["Harness-Verified"])
        self.assertEqual(["codex", "claude", "codex", "claude"], [call[0] for call in self.calls])
        self.assertEqual(["codex", "claude", "codex", "claude"],
                         [c["trailers"]["Harness-Agent"] for c in commits[:4]])
        self.assertTrue(commits[0]["message"].startswith("harness(demo): implement round 1\n\n구현을 마쳤습니다."))
        self.assertNotIn("RAW LOG NOISE", commits[0]["message"])
        self.assertIn("Fix the thing.", commits[1]["message"])
        self.assertTrue(commits[4]["message"].startswith("harness(demo): verify pass"))
        self.assertIn("Harness-Command: python -c", commits[4]["message"])
        # The next implement round sees the review findings from the review commit.
        self.assertIn("Previous review findings\nFix the thing.", self.calls[2][2])
        self.assertIn(orchestrator.IMPLEMENT_SCOPE, self.calls[2][2])
        self.assertNotIn(orchestrator.IMPLEMENT_SCOPE, self.calls[0][2])
        self.assertEqual(["1", "0"], [commits[1]["trailers"]["Harness-Blocking"],
                                      commits[3]["trailers"]["Harness-Blocking"]])
        self.assertIn(orchestrator.REVIEW_INSTRUCTIONS, self.calls[1][2])
        self.assertNotIn("후속 과제", (self.gh_state / "body.md").read_text(encoding="utf-8"))
        for commit in commits:
            self.assertEqual("harness", run_git(self.worktree, "log", "-1", "--format=%an", commit["sha"]))
        self.assertEqual(run_git(self.worktree, "rev-parse", "HEAD"),
                         run_git(self.origin, "rev-parse", "harness/demo"))
        self.assertIn("pr create --base main --head harness/demo --title 데모 작업",
                      (self.gh_state / "calls.log").read_text(encoding="utf-8"))
        self.assertFalse((self.state / "locks" / "demo.json").exists())
        self.assertFalse((self.state / "tasks.sqlite3").exists())

    def test_approved_review_with_follow_ups_reaches_the_pr_body(self):
        self.merge_spec()
        review = ("## Blocking\nNone\n\n## Follow-ups\n- 경계 상황을 더 막자.\n\nBLOCKING: 0\nVERDICT: APPROVE\n")
        with patch.object(orchestrator, "run_agent", side_effect=self.agent((review,))):
            self.assertEqual(0, self.run_cli(), self.stderr)
        self.assertEqual([("implement", None), ("review", "APPROVE"), ("verify", "pass")], self.steps())
        body = (self.gh_state / "body.md").read_text(encoding="utf-8")
        self.assertIn("## 후속 과제 (리뷰)\n\n- 경계 상황을 더 막자.", body)

    def test_missing_blocking_line_records_question_mark(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(("VERDICT: APPROVE\n",))):
            self.assertEqual(1, self.run_cli("--max-rounds", "1"))
        review = self.branch_commits()[1]
        self.assertEqual(("MISSING", "?"), (review["trailers"]["Harness-Verdict"],
                                            review["trailers"]["Harness-Blocking"]))

    def test_rerun_after_completion_only_opens_the_pr_once(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.run_cli(), self.stderr)
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(0, self.run_cli(), self.stderr)
            agent.assert_not_called()
        self.assertEqual(1, len((self.gh_state / "calls.log").read_text(encoding="utf-8").splitlines()))

    def test_run_resumes_from_stage_computed_from_trailers(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        self.assertEqual([("implement", None)], self.steps())
        self.assertEqual(run_git(self.worktree, "rev-parse", "HEAD"), run_git(self.origin, "rev-parse", "harness/demo"))
        self.calls.clear()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.run_cli(), self.stderr)
        self.assertEqual(["review"], [call[1] for call in self.calls])
        self.assertEqual([("implement", None), ("review", "APPROVE"), ("verify", "pass")], self.steps())

    def test_commit_without_trailers_stops_the_run(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        run_git(self.worktree, *IDENT, "commit", "--allow-empty", "-m", "manual change")
        self.calls.clear()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(1, self.run_cli())
        self.assertEqual([], self.calls)
        self.assertIn("트레일러 없는 커밋", self.stderr)

    def test_uncommitted_changes_stop_the_run(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        (self.worktree / "stray.txt").write_text("x", encoding="utf-8")
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(1, self.run_cli())
        self.assertIn("커밋 안 된 변경", self.stderr)

    def test_failed_verification_leaves_a_fail_commit(self):
        self.set_spec(SPEC.replace("assert Path('result.txt').exists()", "raise SystemExit(7)"))
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(1, self.run_cli())
        self.assertEqual([("implement", None), ("review", "APPROVE"), ("verify", "fail")], self.steps())
        self.assertEqual(run_git(self.worktree, "rev-parse", "HEAD"), run_git(self.origin, "rev-parse", "harness/demo"))
        self.assertFalse((self.gh_state / "calls.log").exists())
        # A failing verify is re-run, not skipped.
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(1, self.run_cli())
            agent.assert_not_called()
        self.assertEqual("fail", self.steps()[-1][1])
        self.assertEqual(4, len(self.steps()))

    def test_missing_verify_command_fails_before_any_work(self):
        self.set_spec(SPEC.replace("```\npython -c \"from pathlib import Path; assert Path('result.txt').exists()\"\n```", ""))
        self.merge_spec()
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(1, self.run_cli())
            agent.assert_not_called()
        self.assertFalse(self.worktree.exists())

    def test_live_lock_refuses_the_run(self):
        self.merge_spec()
        (self.state / "locks").mkdir(parents=True)
        (self.state / "locks" / "demo.json").write_text(
            json.dumps({"pid": os.getpid(), "step": "implement"}), encoding="utf-8")
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(1, self.run_cli())
            agent.assert_not_called()
        self.assertIn("이미 실행 중", self.stderr)

    def test_live_lock_is_reported_even_while_the_worktree_is_dirty(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        (self.worktree / "half-written.txt").write_text("x", encoding="utf-8")
        (self.state / "locks").mkdir(parents=True, exist_ok=True)
        (self.state / "locks" / "demo.json").write_text(
            json.dumps({"pid": os.getpid(), "step": "implement"}), encoding="utf-8")
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(1, self.run_cli())
            agent.assert_not_called()
        self.assertIn("이미 실행 중", self.stderr)
        self.assertNotIn("커밋 안 된 변경", self.stderr)

    def test_rerun_after_the_pr_is_merged_does_nothing(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.run_cli(), self.stderr)
        run_git(self.root, "fetch", "origin")
        run_git(self.root, *IDENT, "merge", "--no-ff", "-m", "merge", "origin/harness/demo")
        run_git(self.root, "push", "origin", "main")
        with patch.object(orchestrator, "run_agent") as agent:
            self.assertEqual(0, self.run_cli(), self.stderr)
            agent.assert_not_called()
        self.assertEqual(1, len((self.gh_state / "calls.log").read_text(encoding="utf-8").splitlines()))
        self.assertEqual(3, len(orchestrator.read_commits(self.worktree, merged_task="demo")))

    def test_trailer_keeps_inner_spaces_of_the_command(self):
        command = 'python -c "print(\'a  b\')"'
        message = orchestrator.build_message("s", "body", [("Harness-Command", command), ("Harness-Task", "a\nb")])
        trailers = orchestrator.parse_trailers(message)
        self.assertEqual(command, trailers["Harness-Command"])
        self.assertEqual("a b", trailers["Harness-Task"])

    def test_sync_and_planning_happen_under_the_lock(self):
        """Nothing that can move HEAD runs before the task lock is held."""
        self.merge_spec()
        lock = self.state / "locks" / "demo.json"
        seen = []
        real_sync, real_read = orchestrator.sync_remote, orchestrator.read_commits

        def sync(worktree, task_id):
            seen.append(("sync", orchestrator.read_lock(lock)))
            return real_sync(worktree, task_id)

        def read(cwd, ref="HEAD", merged_task=None):
            if merged_task is not None:
                seen.append(("plan", orchestrator.read_lock(lock)))
            return real_read(cwd, ref, merged_task)

        steps_in_lock = []

        def agent(name, phase, prompt, cwd, log, timeout):
            steps_in_lock.append(orchestrator.read_lock(lock)["step"])
            return self.agent()(name, phase, prompt, cwd, log, timeout)

        with patch.object(orchestrator, "sync_remote", sync), \
                patch.object(orchestrator, "read_commits", read), \
                patch.object(orchestrator, "run_agent", side_effect=agent):
            self.assertEqual(0, self.run_cli(), self.stderr)
        self.assertTrue(seen)
        for kind, info in seen:
            with self.subTest(kind):
                self.assertIsNotNone(info)
                self.assertEqual(os.getpid(), info["pid"])
        # The lock names the real step while the agent runs (the guard depends on it).
        self.assertEqual(["implement", "review"], steps_in_lock)
        self.assertFalse(lock.exists())

    def test_raw_log_is_never_committed_when_final_response_is_missing(self):
        self.merge_spec()

        def agent(name, phase, prompt, cwd, log, timeout):
            log.write_text("SECRET-RAW-LOG\n", encoding="utf-8")
            (Path(cwd) / "result.txt").write_text("x", encoding="utf-8")
            final = log.with_name(log.stem + "-final.md")
            final.write_text("", encoding="utf-8")
            if phase == "implement":
                return final
            raise ValueError("stop after implement")

        with patch.object(orchestrator, "run_agent", side_effect=agent):
            self.assertEqual(1, self.run_cli())
        self.assertNotIn("SECRET-RAW-LOG", run_git(self.worktree, "log", "--format=%B", "origin/main..HEAD"))
        self.assertNotIn("SECRET-RAW-LOG", run_git(self.origin, "log", "--format=%B", "harness/demo"))

    def test_pending_commit_is_pushed_before_the_next_phase(self):
        self.merge_spec()
        real_push = orchestrator.push_branch

        def failing_push(worktree, task_id):
            raise ValueError("push 실패 (커밋은 로컬에 남았습니다): offline")

        with patch.object(orchestrator, "run_agent", side_effect=self.agent()), \
                patch.object(orchestrator, "push_branch", failing_push):
            self.assertEqual(1, self.run_cli())
        self.assertEqual([("implement", None)], self.steps())
        self.calls.clear()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()) as agent, \
                patch.object(orchestrator, "push_branch", failing_push):
            self.assertEqual(1, self.run_cli())
            agent.assert_not_called()
        # Once the remote is back, the pending commit is published and the run continues.
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()), \
                patch.object(orchestrator, "push_branch", real_push):
            self.assertEqual(0, self.run_cli(), self.stderr)
        self.assertEqual(run_git(self.worktree, "rev-parse", "HEAD"), run_git(self.origin, "rev-parse", "harness/demo"))

    def complete_run_then_rewind_local(self):
        """Origin ends at review; the local branch is stale at implement (as in a second clone)."""
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.run_cli(), self.stderr)
        review = run_git(self.worktree, "rev-parse", "HEAD~1")
        implement = run_git(self.worktree, "rev-parse", "HEAD~2")
        run_git(self.origin, "update-ref", "refs/heads/harness/demo", review)
        run_git(self.worktree, "reset", "--hard", implement)
        run_git(self.root, "update-ref", "-d", "refs/remotes/origin/harness/demo")
        self.calls.clear()
        return implement, review

    def test_stale_local_branch_fast_forwards_and_skips_review(self):
        _, review = self.complete_run_then_rewind_local()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()) as agent:
            self.assertEqual(0, self.run_cli(), self.stderr)
            agent.assert_not_called()
        self.assertEqual([("implement", None), ("review", "APPROVE"), ("verify", "pass")], self.steps())
        self.assertEqual(review, run_git(self.worktree, "rev-parse", "HEAD~1"))

    def test_two_clones_stale_clone_resumes_at_verify(self):
        """Clone A publishes review; clone B, still at implement locally, must not review again."""
        self.merge_spec()
        # Clone A implements and pushes, then stops.
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        # Clone B is a separate clone whose harness worktree holds only the implement commit.
        clone_b = self.root.parent / "clone-b"
        run_git(self.root.parent, "clone", str(self.origin), str(clone_b))
        worktree_b = orchestrator.ensure_worktree(clone_b, clone_b / ".harness", "demo")
        implement = run_git(worktree_b, "rev-parse", "HEAD")
        self.assertEqual([("implement", None)], [(c["trailers"]["Harness-Step"], None)
                                                 for c in orchestrator.read_commits(worktree_b)])
        # Clone A reviews and pushes the review, then stops before verify.
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()), \
                patch.object(orchestrator.Task, "verify", side_effect=ValueError("stop before verify")):
            self.assertEqual(1, self.run_cli())
        review = run_git(self.origin, "rev-parse", "harness/demo")
        self.assertEqual(implement, run_git(self.origin, "rev-parse", "harness/demo~1"))
        self.calls.clear()
        # Clone B runs: it fast-forwards to the published review and goes straight to verify.
        stderr = io.StringIO()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()) as agent, \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, orchestrator.main(["run", "demo", "codex"], cwd=clone_b), stderr.getvalue())
            agent.assert_not_called()
        commits = list(reversed(orchestrator.read_commits(worktree_b)))
        self.assertEqual(["implement", "review", "verify"], [c["trailers"]["Harness-Step"] for c in commits])
        self.assertEqual(review, commits[1]["sha"])
        self.assertEqual("pass", commits[2]["trailers"]["Harness-Result"])
        self.assertEqual(commits[2]["sha"], run_git(self.origin, "rev-parse", "harness/demo"))

    def test_single_branch_clone_resumes_task_branch_after_main_advanced(self):
        """A clone tracking only main must start harness/<id> from origin's branch, not origin/main."""
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        implement = run_git(self.origin, "rev-parse", "harness/demo")
        run_git(self.root, *IDENT, "commit", "--allow-empty", "-m", "main moves on")
        run_git(self.root, "push", "origin", "main")
        self.calls.clear()
        clone_b = self.root.parent / "clone-single"
        run_git(self.root.parent, "clone", "--single-branch", "--branch", "main", str(self.origin), str(clone_b))
        self.assertEqual("", run_git(clone_b, "branch", "-r", "--list", "origin/harness/*"))
        stderr = io.StringIO()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, orchestrator.main(["run", "demo", "codex"], cwd=clone_b), stderr.getvalue())
        self.assertEqual(["review"], [phase for _, phase, _ in self.calls])
        commits = list(reversed(orchestrator.read_commits(clone_b / ".harness" / "worktrees" / "demo")))
        self.assertEqual(["implement", "review", "verify"], [c["trailers"]["Harness-Step"] for c in commits])
        self.assertEqual(implement, commits[0]["sha"])

    def test_diverged_local_and_remote_exits_1_without_agent(self):
        self.complete_run_then_rewind_local()
        (self.worktree / "local.txt").write_text("local", encoding="utf-8")
        run_git(self.worktree, "add", "local.txt")
        run_git(self.worktree, *IDENT, "commit", "-m", "local only")
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()) as agent:
            self.assertEqual(1, self.run_cli())
            agent.assert_not_called()
        self.assertIn("로컬 harness/demo와 origin/harness/demo가 갈라졌습니다", self.stderr)

    def test_tree_changed_during_verify_is_not_recorded_as_pass(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(("REQUEST_CHANGES", "APPROVE"))):
            self.assertEqual(1, self.run_cli("--max-rounds", "1"))

        def tamper(command, cwd, log, timeout, **kwargs):
            (self.worktree / "late.txt").write_text("late", encoding="utf-8")

        with patch.object(orchestrator, "run_agent", side_effect=self.agent(("APPROVE",))), \
                patch.object(orchestrator, "run_logged", tamper):
            self.assertEqual(1, self.run_cli("--max-rounds", "1"))
        self.assertNotIn("verify", [step for step, _ in self.steps()])

    def test_rerun_after_completion_needs_no_push(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.run_cli(), self.stderr)
        with patch.object(orchestrator, "push_branch", side_effect=ValueError("offline")):
            self.assertEqual(0, self.run_cli(), self.stderr)

    def test_resume_reviews_with_counterpart_of_the_implementer(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())  # codex implemented
        self.calls.clear()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.cli("run", "demo", "claude"), self.stderr)
        self.assertEqual([("claude", "review")], [(call[0], call[1]) for call in self.calls])

    def test_status_keeps_history_after_the_branch_is_merged(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent()):
            self.assertEqual(0, self.run_cli(), self.stderr)
        run_git(self.root, "fetch", "origin")
        run_git(self.root, *IDENT, "merge", "--no-ff", "-m", "merge", "origin/harness/demo")
        run_git(self.root, "push", "origin", "main")
        self.assertEqual("", run_git(self.root, "log", "origin/main..origin/harness/demo"))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(0, orchestrator.main(["status", "demo"], cwd=self.root))
        self.assertIn("next step: done", stdout.getvalue())
        self.assertIn("last verdict: APPROVE", stdout.getvalue())

    def test_status_reads_stage_from_git(self):
        self.merge_spec()
        with patch.object(orchestrator, "run_agent", side_effect=self.agent(crash_review=True)):
            self.assertEqual(1, self.run_cli())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(0, orchestrator.main(["status", "demo"], cwd=self.root))
        text = stdout.getvalue()
        self.assertRegex(text, r"next step: review")
        self.assertIn("pushed: yes", text)
        self.assertIn("pr: -", text)
        # A fresh clone without the local branch still sees the history on origin.
        run_git(self.root, "worktree", "remove", "--force", str(self.worktree))
        run_git(self.root, "branch", "-D", "harness/demo")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(0, orchestrator.main(["status", "demo"], cwd=self.root))
        self.assertRegex(stdout.getvalue(), r"next step: review")
        self.assertIn("pushed: yes", stdout.getvalue())
        self.assertFalse((self.state / "tasks.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
