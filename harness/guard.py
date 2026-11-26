"""Claude Code PreToolUse hook: allow file edits only where the harness permits them.

- Main checkout: only task specifications (docs/tasks/*.md).
- Harness state (.harness/ database and logs): never.
- Task worktree (.harness/worktrees/<id>): only while that task is running:implement.
- Files outside this repository: allowed.
- Bash: no approving specifications and no touching the harness database.

Set HARNESS_GUARD=off in the shell that launches the agent to maintain the harness itself.
The agent cannot change that variable for the hook process.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path, PurePosixPath

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# The subcommand position: "orchestrator[.py]", optional global options, then "approve".
APPROVE_COMMAND = re.compile(r"orchestrator(?:\.py)?[\"']?(?:\s+--?[\w-]+(?:[=\s]+[^\s-]\S*)?)*\s+[\"']?approve\b")


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            encoding="utf-8", errors="replace", timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None


def existing_dir(path):
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return None


def task_phase(state, task_id):
    database = state / "tasks.sqlite3"
    if not database.is_file():
        return None
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=5)) as db:
        row = db.execute("SELECT phase FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row[0] if row else None


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
                "사용자 승인 후 `python -m harness.orchestrator run ...`으로 진행하세요.")
    worktrees = state / "worktrees"
    if toplevel.parent == worktrees:
        try:
            phase = task_phase(state, toplevel.name)
        except sqlite3.Error as exc:
            return f"작업 상태를 확인할 수 없습니다: {exc}"
        if phase == "running:implement":
            return None
        return (f"작업 {toplevel.name}의 worktree는 하네스 implement 단계에서만 수정할 수 있습니다 "
                f"(현재 단계: {phase or '없음'}).")
    return None


def decide_bash(command, env=os.environ):
    """Return None to allow, or a reason string to deny. Best effort: it reads the command text only."""
    if env.get("HARNESS_GUARD") == "off":
        return None
    if APPROVE_COMMAND.search(command):
        return "명세 승인(approve)은 사람만 할 수 있습니다. 사용자에게 터미널에서 직접 실행해 달라고 요청하세요."
    if "tasks.sqlite3" in command:
        return "하네스 상태 DB는 하네스만 수정할 수 있습니다. 상태는 `orchestrator status <작업 ID>`로 확인하세요."
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
