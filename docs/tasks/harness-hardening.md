# 하네스 보강: 판정 파싱, 오래된 브랜치, 명세 게이트, 가드 위치, 라벨 우회

## 목표
`harness-git-flow`(PR #2)에서 리뷰가 남긴 미해결 지적과 운영 중 발견한 우회 경로를 닫는다. 리뷰 판정, 단계 재실행, CI 게이트, 가드가 에이전트의 실수나 우회로 잘못된 승인을 만들지 않게 한다.

## 범위
- 포함
  1. 리뷰 판정을 응답의 마지막 비어 있지 않은 줄에서만 읽는다.
  2. `run`이 오래된 로컬 `harness/<id>` 브랜치로 이미 원격에 기록된 단계를 다시 실행하지 않게 한다.
  3. `spec/<id>` 게이트가 base에 이미 같은 명세가 있으면 실패하게 한다.
  4. 가드 훅이 항상 main 체크아웃의 `harness/guard.py`를 실행하게 한다 (worktree의 가드를 쓰지 않는다).
  5. 에이전트가 `harness-maintenance` 라벨로 게이트를 우회하지 못하게 Bash 가드를 보강한다.
  - 위 항목의 테스트와 `docs/agent-collaboration.md` 갱신.
- 제외
  - 트레일러 서명 등 위조 방지.
  - GitHub 저장소 설정(ruleset, 라벨 권한) 변경. 필요하면 문서에 사람이 할 일로 적는다.
  - Codex 대화형 세션 훅.

## 변경 대상
- `harness/orchestrator.py`: `parse_verdict`, `ensure_worktree`, `pending_push`, `run_task`(단계 계산 전 원격 동기화)
- `harness/gate.py`: `check_spec_branch`
- `harness/guard.py`, `.claude/settings.json`: 훅 실행 경로
- `tests/test_harness.py`, `tests/test_gate.py`, `tests/test_guard.py`
- `docs/agent-collaboration.md`

## 동작 명세

### 1. 판정 파싱
- 리뷰어 응답에서 끝의 빈 줄을 뺀 마지막 줄이 정확히 `VERDICT: APPROVE`(앞뒤 공백 허용)일 때만 `APPROVE`.
- 마지막 줄이 정확히 `VERDICT: REQUEST_CHANGES`이면 `REQUEST_CHANGES`. 그 밖의 경우는 모두 `MISSING`.
- 예: 본문 중간에 `VERDICT: APPROVE`를 인용하고 마지막 줄이 지적 문장이면 `MISSING`.

### 2. 오래된 로컬 브랜치
- `run`은 잠금을 잡은 뒤, 단계를 계산하기 전에 `git fetch origin harness/<id>`를 한다.
  - 로컬이 원격의 조상이고 worktree가 깨끗하면 원격으로 fast-forward한 뒤 단계를 계산한다.
  - 원격이 로컬의 조상이면(로컬에 push 안 된 커밋) 지금처럼 push부터 한다.
  - 둘이 갈라졌으면 `로컬 harness/<id>와 origin/harness/<id>가 갈라졌습니다` 오류, 종료 코드 1. 에이전트를 실행하지 않는다.
- 원격 브랜치가 없으면 지금과 같다.

### 3. 명세 게이트
- `spec/<id>` 검사에 조건 추가: base SHA에 `docs/tasks/<id>.md`가 있으면 실패 (`이미 승인된 명세입니다`).

### 4. 가드 위치
- 훅 명령이 `$CLAUDE_PROJECT_DIR`가 worktree여도 main 체크아웃(`git rev-parse --git-common-dir`의 부모)의 `harness/guard.py`를 실행한다.
  - 예: `.claude/settings.json`은 작은 진입 스크립트를 부르고, 진입 스크립트가 main 체크아웃의 가드를 찾아 실행한다. 진입 스크립트도 main 체크아웃의 것을 쓴다는 것을 테스트로 보인다.
- 결과: implement 중 worktree의 `harness/guard.py`를 고쳐도 그 실행 중 판단은 바뀌지 않는다.
- main 체크아웃의 가드를 찾지 못하면 편집·Bash를 거부한다 (실패 시 닫힘).

### 5. 라벨 우회
- Bash 가드 거부 목록에 추가: `harness-maintenance` 문자열을 포함하는 `gh pr edit`, `gh pr create`, `gh label`, `gh api` 명령.
- 문서에 "라벨 부여는 사람만 한다"를 적는다.

## 완료 조건
- [ ] `parse_verdict`: 마지막 줄 APPROVE → APPROVE, 중간 APPROVE + 마지막 줄 지적 → MISSING, 마지막 줄 REQUEST_CHANGES → REQUEST_CHANGES, 끝의 빈 줄 무시 테스트.
- [ ] 두 클론 테스트: 클론 A가 review까지 push한 뒤 클론 B(implement까지만 있는 로컬)가 `run`하면 review를 다시 실행하지 않고 verify로 진행한다.
- [ ] 갈라진 로컬·원격이면 에이전트를 부르지 않고 종료 코드 1인 테스트.
- [ ] `gate`: base에 같은 명세가 있는 `spec/<id>` PR 실패 테스트.
- [ ] 가드: worktree의 `harness/guard.py`를 모든 편집을 허용하도록 바꿔도 훅 판단이 main 체크아웃 가드를 따른다는 테스트, main 가드를 못 찾으면 거부한다는 테스트.
- [ ] Bash 가드: `gh pr edit 3 --add-label harness-maintenance`, `gh label create harness-maintenance`, `gh api ... -f labels[]=harness-maintenance` 거부, `gh pr view 3` 허용 테스트.
- [ ] 기존 테스트 전부 통과.

## 검증 명령
```
python -m unittest discover -s tests
```

## 가정
- `harness-git-flow`(PR #2)가 먼저 main에 머지된다. 이 작업은 새 흐름(`propose` → 명세 PR 머지 → `run`)으로 진행하는 첫 작업이다.
- 4번은 이 작업의 implement 중에도 적용된다. 이 작업이 바꾸는 가드는 main 체크아웃의 가드가 아니므로 자기 자신을 잠그지 않는다.
- 라벨 우회 차단은 Bash 문자열 검사라 완전하지 않다. 사람이 PR에서 라벨을 확인하는 것이 최종 방어선이다.

## 열린 질문
없음
