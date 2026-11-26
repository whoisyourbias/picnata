"""CI gate for pull requests into main, decided from commit trailers instead of branch names alone.

    python -m harness.gate --base <base SHA> --head <head SHA> --branch <head branch> [--label <label>...]

- label harness-maintenance: pass.
- spec/<id>: the only change is adding docs/tasks/<id>.md.
- harness/<id>: the spec is on the base and untouched, HEAD is a passing verify commit for a tree that
  an APPROVE review commit approved.
- anything else: fail.
Trailers are not signed; the last line of defence is the human who merges the pull request.
"""

import argparse
import re
import sys

from harness.orchestrator import git, git_ok, parse_trailers

MAINTENANCE_LABEL = "harness-maintenance"
TASK_ID = r"[a-z][a-z0-9-]{0,63}"


def check_spec_branch(cwd, base, head, task_id):
    path = f"docs/tasks/{task_id}.md"
    if git_ok(cwd, "cat-file", "-e", f"{base}:{path}"):
        return [f"{path}가 base에 이미 있습니다. 이미 승인된 명세입니다."]
    changes = git(cwd, "diff", "--name-status", "--no-renames", f"{base}...{head}").splitlines()
    if changes != [f"A\t{path}"]:
        return [f"spec/{task_id} 브랜치는 {path} 추가 하나만 포함해야 합니다 (변경: {', '.join(changes) or '없음'})."]
    return []


def check_harness_branch(cwd, base, head, task_id):
    path = f"docs/tasks/{task_id}.md"
    if not git_ok(cwd, "cat-file", "-e", f"{base}:{path}"):
        return [f"{path}가 base(main)에 없습니다. 명세 PR(spec/{task_id})이 먼저 머지되어야 합니다."]
    errors = []
    if git(cwd, "diff", "--name-only", f"{base}...{head}", "--", path):
        errors.append(f"구현 브랜치가 승인된 명세 {path}를 수정했습니다.")
    commits = []
    for chunk in git(cwd, "log", "--format=%H%x1f%B%x1e", f"{base}..{head}").split("\x1e"):
        if chunk.strip():
            sha, _, message = chunk.strip().partition("\x1f")
            commits.append((sha, parse_trailers(message)))
    head_sha = git(cwd, "rev-parse", head)
    tip = commits[0][1] if commits and commits[0][0] == head_sha else {}
    if tip.get("Harness-Step") != "verify" or tip.get("Harness-Result") != "pass":
        return errors + ["HEAD가 Harness-Step: verify, Harness-Result: pass 커밋이 아닙니다."]
    verified = tip.get("Harness-Verified", "")
    if not re.fullmatch(r"[0-9a-f]{40}", verified) or not git_ok(cwd, "cat-file", "-e", f"{verified}^{{commit}}"):
        return errors + ["Harness-Verified 커밋을 찾을 수 없습니다."]
    if git(cwd, "rev-parse", f"{verified}^{{tree}}") != git(cwd, "rev-parse", f"{head_sha}^{{tree}}"):
        errors.append("검증한 커밋의 트리가 HEAD와 다릅니다 (검증 뒤에 내용이 바뀌었습니다).")
    if not any(trailers.get("Harness-Step") == "review" and trailers.get("Harness-Verdict") == "APPROVE"
               and trailers.get("Harness-Reviewed") == verified for _, trailers in commits):
        errors.append("검증한 커밋을 Harness-Reviewed로 가진 APPROVE 리뷰 커밋이 없습니다.")
    return errors


def check(cwd, base, head, branch, labels=()):
    """Return a list of failure reasons; empty means the pull request may merge."""
    if MAINTENANCE_LABEL in labels:
        return []
    if match := re.fullmatch(rf"spec/({TASK_ID})", branch):
        return check_spec_branch(cwd, base, head, match.group(1))
    if match := re.fullmatch(rf"harness/({TASK_ID})", branch):
        return check_harness_branch(cwd, base, head, match.group(1))
    return [f"브랜치 {branch}는 main에 머지할 수 없습니다. spec/<작업 ID>, harness/<작업 ID> 브랜치만 허용되며 "
            f"하네스 자체 변경은 {MAINTENANCE_LABEL} 라벨을 붙이세요."]


def main(argv=None, cwd=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--label", nargs="*", action="extend", default=[])
    parser.add_argument("--repo", help="검사할 git 저장소 경로 (기본: 현재 디렉터리)")
    args = parser.parse_args(argv)
    if args.repo:
        cwd = args.repo
    try:
        errors = check(cwd,args.base, args.head, args.branch, {label for label in args.label if label})
    except (ValueError, OSError) as exc:
        errors = [f"검사하지 못했습니다: {exc}"]
    for error in errors:
        print(f"harness-gate: {error}", file=sys.stderr)
    if not errors:
        print("harness-gate: 통과")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
