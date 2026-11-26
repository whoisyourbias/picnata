import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from harness import gate, orchestrator

IDENT = ["-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def run_git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          encoding="utf-8").stdout.strip()


class GateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        run_git(self.root, "init")
        run_git(self.root, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.root / "README.md").write_text("hi", encoding="utf-8")
        run_git(self.root, "add", "-A")
        run_git(self.root, *IDENT, "commit", "-m", "init")

    def base_with_spec(self):
        path = self.root / "docs" / "tasks" / "demo.md"
        path.parent.mkdir(parents=True)
        path.write_text("# spec\n", encoding="utf-8")
        run_git(self.root, "add", "-A")
        run_git(self.root, *IDENT, "commit", "-m", "spec")

    def sha(self, ref="HEAD"):
        return run_git(self.root, "rev-parse", ref)

    def check(self, branch, base, labels=()):
        return gate.check(self.root, base, self.sha(), branch, set(labels))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        run_git(self.root, "add", "-A")

    def step(self, step, body="", **trailers):
        pairs = [("Harness-Task", "demo"), ("Harness-Step", step), *trailers.items()]
        return orchestrator.harness_commit(self.root, orchestrator.build_message(
            f"harness(demo): {step}", body, [(key.replace("_", "-"), value) for key, value in pairs]))

    def full_branch(self, verdict="APPROVE", result="pass", tamper=False):
        """implement -> review -> verify on harness/demo; returns the base SHA."""
        self.base_with_spec()
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "harness/demo")
        self.write("result.txt", "done")
        implemented = self.step("implement", Harness_Agent="codex", Harness_Round="1")
        self.step("review", Harness_Reviewed=implemented, Harness_Verdict=verdict)
        if tamper:
            self.write("result.txt", "changed after review")
            self.step("implement", Harness_Agent="codex", Harness_Round="2")
        self.step("verify", Harness_Verified=implemented, Harness_Result=result, Harness_Command="x")
        return base

    # spec branches

    def test_spec_branch_adding_only_the_spec_passes(self):
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "spec/demo")
        self.write("docs/tasks/demo.md", "# spec\n")
        run_git(self.root, *IDENT, "commit", "-m", "spec")
        self.assertEqual([], self.check("spec/demo", base))

    def test_spec_branch_with_other_files_fails(self):
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "spec/demo")
        self.write("docs/tasks/demo.md", "# spec\n")
        self.write("harness/evil.py", "x")
        run_git(self.root, *IDENT, "commit", "-m", "spec")
        self.assertTrue(self.check("spec/demo", base))

    def test_spec_branch_for_another_task_fails(self):
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "spec/demo")
        self.write("docs/tasks/other.md", "# spec\n")
        run_git(self.root, *IDENT, "commit", "-m", "spec")
        self.assertTrue(self.check("spec/demo", base))

    # harness branches

    def test_complete_harness_branch_passes(self):
        base = self.full_branch()
        self.assertEqual([], self.check("harness/demo", base))

    def test_missing_verify_fails(self):
        self.base_with_spec()
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "harness/demo")
        self.write("result.txt", "done")
        implemented = self.step("implement", Harness_Round="1")
        self.step("review", Harness_Reviewed=implemented, Harness_Verdict="APPROVE")
        self.assertTrue(self.check("harness/demo", base))

    def test_failed_verify_fails(self):
        base = self.full_branch(result="fail")
        self.assertTrue(self.check("harness/demo", base))

    def test_tree_mismatch_fails(self):
        base = self.full_branch(tamper=True)
        errors = self.check("harness/demo", base)
        self.assertTrue(any("트리" in error for error in errors), errors)

    def test_missing_approve_fails(self):
        base = self.full_branch(verdict="REQUEST_CHANGES")
        errors = self.check("harness/demo", base)
        self.assertTrue(any("APPROVE" in error for error in errors), errors)

    def test_modified_spec_fails(self):
        base = self.full_branch()
        self.write("docs/tasks/demo.md", "# edited\n")
        run_git(self.root, *IDENT, "commit", "-m", "sneaky")
        self.assertTrue(self.check("harness/demo", base))
        # even a harness-looking verify on top does not repair a modified spec
        run_git(self.root, "reset", "-q", "--hard", "HEAD~1")
        self.write("docs/tasks/demo.md", "# edited\n")
        implemented = self.step("implement", Harness_Round="2")
        self.step("review", Harness_Reviewed=implemented, Harness_Verdict="APPROVE")
        self.step("verify", Harness_Verified=implemented, Harness_Result="pass", Harness_Command="x")
        self.assertTrue(any("명세" in error for error in self.check("harness/demo", base)))

    def test_spec_missing_on_base_fails(self):
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "harness/demo")
        self.write("result.txt", "done")
        implemented = self.step("implement", Harness_Round="1")
        self.step("review", Harness_Reviewed=implemented, Harness_Verdict="APPROVE")
        self.step("verify", Harness_Verified=implemented, Harness_Result="pass", Harness_Command="x")
        self.assertTrue(self.check("harness/demo", base))

    # labels and other branches

    def test_maintenance_label_passes_any_branch(self):
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "feature/x")
        self.write("harness/x.py", "x")
        run_git(self.root, *IDENT, "commit", "-m", "x")
        self.assertEqual([], self.check("feature/x", base, {"harness-maintenance"}))

    def test_other_branches_fail(self):
        base = self.sha()
        run_git(self.root, "checkout", "-q", "-b", "feature/x")
        self.write("x.txt", "x")
        run_git(self.root, *IDENT, "commit", "-m", "x")
        self.assertTrue(self.check("feature/x", base))
        self.assertTrue(self.check("spec/Bad_Name", base))

    def test_cli_exit_codes(self):
        base = self.full_branch()
        head = self.sha()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, gate.main(["--base", base, "--head", head, "--branch", "harness/demo"], cwd=self.root))
            self.assertEqual(0, gate.main(["--base", base, "--head", head, "--branch", "x/y",
                                           "--label", "bug", "--label", "harness-maintenance"], cwd=self.root))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, gate.main(["--base", base, "--head", head, "--branch", "x/y"], cwd=self.root))


if __name__ == "__main__":
    unittest.main()
