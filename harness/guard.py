"""Claude Code PreToolUse hook: allow file edits only where the harness permits them.

- Main checkout: only task specifications (docs/tasks/*.md).
- Harness state (.harness/ locks and logs): never.
- Task worktree (.harness/worktrees/<id>): only while the lock file .harness/locks/<id>.json
  names an implement step owned by a live process.
- Files outside this repository: allowed.
- Bash: no merging or approving pull requests and no touching the lock files.

The hook command (.claude/settings.json) always runs the main checkout's copy of this file, found
through git's common dir, so editing a worktree copy changes nothing; if it is not found, the hook fails closed.

Set HARNESS_GUARD=off in the shell that launches the agent to maintain the harness itself.
The agent cannot change that variable for the hook process.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GH_MERGE = re.compile(r"\bgh\b[^|;&\n]*\bpr\s+merge\b")
GH_APPROVE = re.compile(r"\bgh\b[^|;&\n]*\bpr\s+review\b[^|;&\n]*(?:--approve\b|\s-a\b)")
GH_LABEL_BYPASS = re.compile(
    r"\bgh\b[^|;&\n]*\b(?:pr\s+(?:edit|create)|label|api)\b[^|;&\n]*harness-maintenance")
LOCKS = re.compile(r"\.harness[/\\]+locks")


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            encoding="utf-8", errors="replace", timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None


def existing_dir(path):
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return None


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.GetLastError() == 5  # access denied: the process exists
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running_step(state, task_id):
    """The step named by a live lock file (.harness/locks/<id>.json), or None."""
    try:
        info = json.loads((state / "locks" / f"{task_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not pid_alive(info.get("pid")):
        return None
    return info.get("step")


def decide(file_path, cwd, env=os.environ):
    """Return None to allow, or a reason string to deny."""
    if env.get("HARNESS_GUARD") == "off":
        return None
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(cwd) / path
    path = path.resolve()
    directory = existing_dir(path.parent)
    if directory is None:
        return None
    toplevel = git(directory, "rev-parse", "--show-toplevel")
    common = git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if toplevel is None or common is None:
        return None
    main_root = Path(common).resolve().parent
    state = main_root / ".harness"
    toplevel = Path(toplevel).resolve()
    if toplevel == main_root:
        relative = PurePosixPath(path.relative_to(main_root).as_posix())
        if relative.parts[:1] == (".harness",):
            return "하네스 상태(.harness/)는 하네스만 수정할 수 있습니다."
        if relative.parent == PurePosixPath("docs/tasks") and relative.suffix == ".md":
            return None
        return ("main 체크아웃은 하네스 밖에서 수정할 수 없습니다. 먼저 docs/tasks/<작업 ID>.md 명세를 쓰고 "
                "`python -m harness.orchestrator propose <작업 ID>`로 명세 PR을 올리세요. 사용자가 머지한 뒤 "
                "`python -m harness.orchestrator run ...`으로 진행합니다.")
    worktrees = state / "worktrees"
    if toplevel.parent == worktrees:
        step = running_step(state, toplevel.name)
        if step == "implement":
            return None
        return (f"작업 {toplevel.name}의 worktree는 하네스 implement 단계에서만 수정할 수 있습니다 "
                f"(현재 단계: {step or '없음'}).")
    return None


def decide_bash(command, env=os.environ):
    """Return None to allow, or a reason string to deny. Best effort: it reads the command text only."""
    if env.get("HARNESS_GUARD") == "off":
        return None
    if GH_MERGE.search(command):
        return "PR 머지는 사람만 할 수 있습니다. 사용자에게 GitHub에서 머지해 달라고 요청하세요."
    if GH_APPROVE.search(command):
        return "PR 승인은 사람만 할 수 있습니다."
    if GH_LABEL_BYPASS.search(command):
        return "harness-maintenance 라벨은 사람만 부여할 수 있습니다."
    if LOCKS.search(command):
        return "하네스 잠금 파일(.harness/locks)은 하네스만 수정할 수 있습니다. 상태는 `orchestrator status <작업 ID>`로 확인하세요."
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("하네스 가드: 훅 입력을 읽을 수 없습니다.", file=sys.stderr)
        return 2
    tool_input = event.get("tool_input") or {}
    if event.get("tool_name") == "Bash":
        reason = decide_bash(str(tool_input.get("command") or ""))
        if reason:
            print(f"하네스 가드: {reason}", file=sys.stderr)
            return 2
        return 0
    if event.get("tool_name") not in EDIT_TOOLS:
        return 0
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0
    try:
        reason = decide(file_path, event.get("cwd") or os.getcwd())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = f"하네스 가드가 경로를 확인하지 못했습니다: {exc}"
    if reason:
        print(f"하네스 가드: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
