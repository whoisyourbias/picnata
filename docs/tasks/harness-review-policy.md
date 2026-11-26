# 리뷰 판정 기준: 차단 지적이 없으면 승인

## 목표
리뷰어가 사소한 경계 상황을 계속 찾아내 implement·review가 끝나지 않는 문제를 막는다. 리뷰는 정확성·보안·명세 위반 같은 차단 지적이 있을 때만 수정을 요구하고, 나머지는 후속 과제로 남긴 채 승인해 verify와 구현 PR로 진행되게 한다.

## 범위
- 포함
  - 리뷰 프롬프트에 심각도 기준(차단 / 후속)과 출력 형식 추가
  - 하네스가 리뷰 출력의 `BLOCKING: <n>` 줄로 판정을 정한다
  - review 커밋에 `Harness-Blocking` 트레일러 추가
  - implement 프롬프트: 직전 리뷰의 차단 지적만 고치고 후속 과제로 범위를 넓히지 않도록 안내
  - 구현 PR 본문에 마지막 APPROVE 리뷰의 후속 과제 절을 넣는다
  - 테스트, `docs/agent-collaboration.md` 갱신
- 제외
  - CI 게이트(`harness/gate.py`) 변경. 게이트는 지금처럼 `Harness-Verdict: APPROVE`만 본다
  - 리뷰어·구현자 선택 방식 (`harness-agent-selection` 명세의 주제)
  - `--max-rounds` 기본값 변경
  - 진행 중인 `harness-windows-tools` 브랜치 수정

## 변경 대상
- `harness/orchestrator.py`: `parse_verdict`, `Task.review`(프롬프트, 커밋 트레일러), `Task.implement`(프롬프트), 구현 PR 본문 생성
- `tests/test_harness.py`
- `docs/agent-collaboration.md`

## 동작 명세

### 심각도 기준 (리뷰 프롬프트에 넣는다, 영어)
- **차단(blocking)**: 아래 중 하나이고 근거(파일 위치와 재현 시나리오)가 있는 지적.
  - 명세의 "동작 명세"나 "완료 조건"을 지키지 않는다 (빠진 기능, 틀린 동작, 빠진 필수 테스트).
  - 일반적인 사용 흐름에서 잘못된 결과, 데이터 손실, 크래시가 난다.
  - 가드, 승인, 게이트 같은 보안·권한 장치를 우회하거나 약하게 만든다.
  - 테스트가 실패하거나, 변경이 기존 테스트를 깨뜨린다.
- **후속(follow-up)**: 그 밖의 모든 지적.
  - 명세가 요구하지 않은 동시 실행·타이밍 경쟁 같은 드문 경계 상황.
  - 추가 방어 코드, 리팩터링, 이름, 문서 표현, 스타일.
  - 명세 범위 밖의 개선 제안.
- 확신이 없으면 후속으로 분류한다.

### 리뷰 출력 형식
- 본문에 `## Blocking`과 `## Follow-ups` 두 절을 쓴다. 해당 없으면 절 본문은 `None`.
- 마지막 두 줄은 정확히:
  ```
  BLOCKING: <차단 지적 수>
  VERDICT: <APPROVE|REQUEST_CHANGES>
  ```
- `BLOCKING: 0`이면 `VERDICT: APPROVE`, 1 이상이면 `VERDICT: REQUEST_CHANGES`.

### 판정 (`parse_verdict`)
- 끝의 빈 줄을 뺀 마지막 줄이 `VERDICT: APPROVE` 또는 `VERDICT: REQUEST_CHANGES`이고, 바로 앞 줄이 `BLOCKING: <0 이상의 정수>`일 때만 판정을 낸다. 아니면 `MISSING`.
- 판정은 `BLOCKING` 수로 정한다: 0이면 `APPROVE`, 1 이상이면 `REQUEST_CHANGES`. `VERDICT` 줄과 수가 어긋나면 수를 따르고, 하네스 출력에 `리뷰 판정과 BLOCKING 수가 어긋나 BLOCKING 수를 따릅니다` 경고를 남긴다.
- 예:
  - `BLOCKING: 0` / `VERDICT: APPROVE` → APPROVE
  - `BLOCKING: 0` / `VERDICT: REQUEST_CHANGES` → APPROVE (경고)
  - `BLOCKING: 2` / `VERDICT: APPROVE` → REQUEST_CHANGES (경고)
  - `VERDICT: APPROVE`만 있고 `BLOCKING` 줄 없음 → MISSING
- review 커밋 트레일러에 `Harness-Blocking: <n>`을 추가한다 (MISSING이면 `Harness-Blocking: ?`). 기존 트레일러는 그대로.

### implement 프롬프트
- 직전 리뷰 지적을 넣을 때 "Fix every item under Blocking. Do not implement Follow-ups unless they are needed to fix a blocking item; keep the change within the task specification." 문장을 덧붙인다.

### 구현 PR 본문
- 마지막 APPROVE review 커밋 본문의 `## Follow-ups` 절 내용이 `None`이 아니면 PR 본문 끝에 `## 후속 과제 (리뷰)` 절로 붙인다. 절이 없으면 생략한다.

## 완료 조건
- [ ] `parse_verdict`: 위 네 예시와, 끝의 빈 줄 무시, `BLOCKING: -1`·`BLOCKING: x` → MISSING 테스트.
- [ ] 어긋난 판정에서 경고가 출력된다는 테스트.
- [ ] 리뷰 프롬프트에 차단·후속 기준, 두 절, 마지막 두 줄 형식이 들어간다는 테스트.
- [ ] review 커밋에 `Harness-Blocking` 트레일러가 들어간다는 테스트 (숫자, `?`).
- [ ] 가짜 리뷰어가 `BLOCKING: 0` + 후속 과제를 내면 run이 verify로 진행하고, 구현 PR 본문(가짜 `gh`에 전달된 본문)에 후속 과제 절이 들어간다는 테스트.
- [ ] implement 프롬프트에 Blocking만 고치라는 문장이 들어간다는 테스트 (직전 리뷰가 있을 때만).
- [ ] 기존 테스트 전부 통과.

## 검증 명령
```
python -m unittest discover -s tests
```

## 가정
- 이 정책은 main 체크아웃의 하네스가 실행하므로, 머지 뒤 `harness-windows-tools`를 다시 `run`하면 그 브랜치의 다음 리뷰부터 새 기준이 적용된다.
- 분류는 리뷰어의 판단에 맡긴다. 하네스는 형식과 수만 검사한다. 리뷰어가 차단 지적을 후속으로 잘못 분류하면 사람이 구현 PR에서 후속 과제 절을 보고 판단한다.
- `harness-agent-selection` 명세는 리뷰어 선택만 다루므로 이 작업과 겹치지 않는다. 둘 다 `Task.review`를 건드리면 나중에 머지되는 쪽이 충돌을 해결한다.

## 열린 질문
없음
