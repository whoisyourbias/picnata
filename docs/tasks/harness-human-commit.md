# 사람이 고친 커밋을 이어받아 리뷰·검증하기 (`run --adopt`)

## 목표
구현 에이전트가 쓸 수 없는 파일(예: `.claude/settings.json`)을 사람이 작업 브랜치에 직접 커밋한 뒤에도, 하네스가 그 커밋을 새 implement 라운드로 기록하고 리뷰와 verify를 거쳐 구현 PR까지 이어가게 한다. 그래서 사람이 한 수정도 `harness-maintenance` 라벨 없이 트레일러 기록이 남는 정식 경로로 머지된다.

## 범위
- 포함
  - `run <id> <agent> --adopt`: 마지막 하네스 커밋 뒤의 트레일러 없는 커밋을 이어받는 기록 커밋을 만든다
  - 이어받기 기록 커밋의 형식과 이어받기를 거부하는 조건
  - 이어받은 라운드의 리뷰어 선택
  - `status`에 이어받기 표시
  - 테스트, `docs/agent-collaboration.md` 갱신
- 제외
  - `--adopt` 없이 트레일러 없는 커밋이 있을 때의 동작 변경 (지금처럼 거부한다)
  - 구현 에이전트가 보호된 설정 파일을 쓸 수 있게 하는 것
  - CI 게이트(`harness/gate.py`) 변경 (게이트는 지금처럼 verify pass, 검증한 트리 일치, 그 트리를 APPROVE한 리뷰 커밋만 본다)
  - 이어받은 커밋의 서명·작성자 검증

## 변경 대상
- `harness/orchestrator.py`: CLI 옵션, `plan_next` 호출 직전의 이어받기 처리, 기록 커밋 생성, `status`, 리뷰어 선택(`Task.review`)
- `tests/test_harness.py`
- `docs/agent-collaboration.md`

## 동작 명세

### CLI
- 변경 전: `run <id> <agent> [--max-rounds N] [--wait SECONDS]`
- 변경 후: `run <id> <agent> [--max-rounds N] [--wait SECONDS] [--adopt]`
- `--adopt` 없이 마지막 하네스 커밋 뒤에 트레일러 없는 커밋이 있으면 지금과 같은 오류(`마지막 하네스 커밋 뒤에 트레일러 없는 커밋이 있습니다...`)에 한 줄을 더한다: `사람이 한 수정이면 --adopt로 이어받을 수 있습니다.` 종료 코드 1.

### 이어받기
`--adopt`가 있고, 잠금을 잡은 뒤 원격 동기화(기존 동작)를 마친 시점에 마지막 하네스 커밋(없으면 `origin/main`) 뒤에 트레일러 없는 커밋이 하나 이상 있으면 단계 계산 전에 다음을 한다.
1. worktree가 깨끗해야 한다 (기존 `ensure_clean`).
2. 이어받을 커밋들이 아래 거부 조건에 걸리지 않는지 확인한다.
3. 빈 커밋(`--allow-empty`) 하나를 만든다. 작성자는 하네스(`harness <harness@example.invalid>`), 형식:
   ```
   harness(<id>): adopt human commits

   <이어받은 커밋마다 한 줄: "<짧은 SHA> <작성자 이름> <제목>">

   Harness-Task: <id>
   Harness-Step: implement
   Harness-Agent: human
   Harness-Round: <현재 최대 라운드 + 1, 하네스 커밋이 없으면 1>
   Harness-Adopted: <이어받은 첫 커밋 SHA>..<이어받은 마지막 커밋 SHA>
   ```
4. 이 커밋을 push한 뒤 기존 흐름대로 단계를 계산한다. 마지막 하네스 커밋이 `Harness-Step: implement`이므로 다음 단계는 review다.
5. 이어받기는 이번 실행의 `--max-rounds`(implement 실행 횟수)에 세지 않는다.
- 이어받을 커밋이 없으면 `--adopt`는 아무 일도 하지 않고 기존처럼 진행한다 (플래그가 있어도 오류가 아니다).

### 이어받기 거부 조건
다음 중 하나면 기록 커밋을 만들지 않고 이유를 출력한 뒤 종료 코드 1.
- 이어받을 커밋 중 머지 커밋(부모 2개)이 있다.
- 이어받을 커밋이 승인된 명세 `docs/tasks/<id>.md`를 수정한다.
- 이어받을 커밋 사이에 `Harness-Step` 트레일러가 있는 커밋이 끼어 있다 (트레일러 없는 연속 구간이 아니다).
- 이어받을 커밋의 합이 `origin/main` 대비 변경 없음이다 (되돌림 등으로 트리가 같다). 이때는 `이어받을 변경이 없습니다`를 출력한다.

### 리뷰어
- 리뷰어는 직전 implement 커밋의 `Harness-Agent` 반대쪽이다. 그 값이 `human`이면 `run`에 준 `<agent>`의 반대쪽 에이전트가 리뷰한다. (예: `run ... claude --adopt` → Codex가 리뷰)

### status
- 이어받은 라운드가 있으면 `adopted: <첫 SHA>..<마지막 SHA> (round <n>)` 줄을 출력한다. 없으면 출력하지 않는다.

### 게이트
- 변경하지 않는다. 이어받기 커밋은 트리를 바꾸지 않으므로 verify가 검증하는 트리와 리뷰가 승인한 트리는 사람이 만든 변경까지 포함해 같다.

## 완료 조건
- [ ] `--adopt` 없이 트레일러 없는 커밋이 있으면 종료 코드 1, 기존 오류 문구와 `--adopt` 안내가 모두 출력되고 에이전트가 호출되지 않는다는 테스트.
- [ ] 가짜 에이전트로 implement → review(REQUEST_CHANGES) 뒤 사람 커밋 1개를 얹고 `run --adopt`하면 기록 커밋이 생기고(트레일러 5개 모두 형식대로, `Harness-Round`는 이전 최대 + 1) review → verify → 구현 PR까지 진행된다는 테스트.
- [ ] 하네스 커밋이 하나도 없는 브랜치에 사람 커밋이 있을 때 `--adopt`하면 `Harness-Round: 1`로 기록된다는 테스트.
- [ ] 사람 커밋이 여러 개일 때 `Harness-Adopted` 범위와 본문 목록이 맞다는 테스트.
- [ ] 이어받은 라운드의 리뷰어가 `run`에 준 에이전트의 반대쪽이라는 테스트 (`claude`/`codex` 두 경우).
- [ ] 거부 조건 네 가지 각각에서 기록 커밋이 만들어지지 않고 종료 코드 1이라는 테스트.
- [ ] 이어받을 커밋이 없을 때 `--adopt`가 기존 동작을 바꾸지 않는다는 테스트.
- [ ] 이어받기가 `--max-rounds`에 세지 않는다는 테스트 (`--max-rounds 1`에서도 이어받은 뒤 review까지 진행).
- [ ] `status`가 이어받은 라운드를 출력하고, 없을 때는 출력하지 않는다는 테스트.
- [ ] `harness/gate.py`가 이어받기 기록이 있는 브랜치(verify pass, 트리 일치, 그 트리의 APPROVE 리뷰)를 통과시킨다는 테스트.
- [ ] 기존 테스트 전부 통과.

## 검증 명령
```
python -m unittest discover -s tests
```

## 가정
- 이어받기는 사람이 한 수정을 하네스 기록에 편입하는 용도이고, 리뷰와 verify가 그 뒤에 반드시 실행되므로 검증을 건너뛰는 경로가 아니다. 그래서 TTY나 사람 확인을 요구하지 않는다. 에이전트가 직접 커밋한 변경도 같은 리뷰·verify를 거친다.
- 에이전트가 worktree를 직접 편집하는 것은 가드가 막는다. 이 작업은 가드를 바꾸지 않는다.
- 이어받은 커밋의 작성자는 검증하지 않는다. 본문 목록에 작성자 이름을 남겨 PR에서 사람이 확인한다.
- 사람이 커밋한 뒤 push는 사람이 하거나, `run`이 기록 커밋과 함께 push한다 (기존 `run`의 push 동작을 따른다).

## 열린 질문
없음
