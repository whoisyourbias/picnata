# 재작업 라운드에서 리뷰가 수렴하게 하기

## 목표
재작업(implement → review를 되풀이하는) 라운드에서 리뷰어가 매번 전체 변경을 처음 보듯 새 차단 지적을 만들어 내지 않게 한다. 라운드가 거듭될수록 차단 지적은 "앞서 지적한 것이 고쳐졌는지"와 "이번 수정이 만든 문제"로 좁혀지고, 나머지는 후속 과제로 PR 본문에 남아 사람이 판단한다.

## 범위
- 포함
  1. 재작업 라운드의 리뷰 입력에 직전 리뷰의 차단 지적 목록과, 직전 리뷰 이후의 변경(증분 diff)을 따로 넣는다.
  2. 리뷰 지침(`REVIEW_INSTRUCTIONS`)에 "재작업 라운드의 차단 기준"과 "조작·동시성 시나리오는 후속" 규칙을 추가한다.
  3. 테스트, `docs/agent-collaboration.md` 갱신.
- 제외
  - 첫 리뷰 라운드(round 1)의 입력과 기준 변경. 첫 리뷰는 지금처럼 전체 diff를 본다.
  - 리뷰 판정 형식(`BLOCKING: n` / `VERDICT:`)과 `parse_review` 변경.
  - 라운드 상한(`--max-rounds`)과 `run`의 흐름 변경.
  - 리뷰어 선택, 구현자 프롬프트 변경.

## 변경 대상
- `harness/orchestrator.py`: `REVIEW_INSTRUCTIONS`, `Task.review`(프롬프트 조립)
- `tests/test_harness.py`
- `docs/agent-collaboration.md`

## 동작 명세

### 재작업 라운드의 리뷰 입력
`Task.review`는 브랜치에 이전 review 커밋이 하나라도 있으면(= 재작업 라운드) 지금의 입력(명세, 커밋 SHA, `origin/main...HEAD` 전체 diff) 뒤에 두 절을 더한다.
1. `Previous blocking findings`: 직전 review 커밋 본문의 `## Blocking` 절 내용. 이전 review 커밋이 `APPROVE`뿐이거나 절이 없으면 `None`.
2. `Changes since the previous review`: `Harness-Reviewed` 트레일러가 가리키는 직전 리뷰 대상 커밋부터 HEAD까지의 diff (`git diff <직전 리뷰 대상 SHA> HEAD`). 그 커밋이 현재 히스토리에 없으면 이 절 대신 `Not available; review the full diff above.`를 넣는다.

첫 리뷰 라운드(이전 review 커밋이 없음)에는 두 절을 넣지 않는다.

### 리뷰 지침에 추가할 규칙 (영어, 기존 문구 뒤)
재작업 라운드(입력에 `Previous blocking findings` 절이 있을 때)에서는 아래에 해당하는 지적만 Blocking이다.
- 직전의 Blocking 지적이 여전히 해결되지 않았다.
- `Changes since the previous review`에 있는 변경이 새로 만든 회귀나 명세 위반이다.
- 명세의 "완료 조건"에 적힌 항목이 충족되지 않았다.

그 밖의 지적은 Follow-up이다. 이전 라운드에서 지적하지 않았고 `Changes since the previous review`에 없는 코드에서 새로 찾은 문제도 Follow-up이다. 다만 첫 리뷰 라운드에서는 이 제한을 적용하지 않는다.

모든 라운드에 적용되는 규칙 (기존 "Follow-up" 목록에 추가):
- 재현하려면 작업자가 설정·로그·다른 세션의 파일을 일부러 조작해야 하거나, 두 프로세스가 같은 순간에 같은 지점을 통과해야 하는 시나리오는 명세의 "완료 조건"에 그 시나리오가 직접 적혀 있지 않은 한 Follow-up이다.

### 판정 형식
- 변경 없음. 출력 절(`## Blocking`, `## Follow-ups`)과 마지막 두 줄 형식은 지금과 같다.

## 완료 조건
- [ ] 첫 리뷰 라운드의 프롬프트에 `Previous blocking findings`와 `Changes since the previous review`가 없다는 테스트.
- [ ] 재작업 라운드의 프롬프트에 직전 review 커밋의 `## Blocking` 본문이 `Previous blocking findings` 아래에 그대로 들어간다는 테스트.
- [ ] 재작업 라운드의 프롬프트에 직전 리뷰 대상 커밋부터 HEAD까지의 diff가 `Changes since the previous review` 아래에 들어가고, 그 이전 라운드에서만 바뀐 줄은 이 절에 들어가지 않는다는 테스트.
- [ ] 직전 리뷰 대상 커밋이 히스토리에 없으면 `Not available` 문구가 들어간다는 테스트.
- [ ] 직전 리뷰가 `APPROVE`(차단 `None`)였던 경우 `Previous blocking findings`가 `None`이라는 테스트.
- [ ] 리뷰 지침에 재작업 라운드 기준 세 항목과 조작·동시성 시나리오 규칙이 들어 있다는 테스트 (문구의 핵심 구절 존재).
- [ ] 판정 형식(`parse_review`)과 `run`의 라운드·단계 계산은 바뀌지 않았다는 기존 테스트 통과.
- [ ] 기존 테스트 전부 통과.

## 검증 명령
```
python -m unittest discover -s tests
```

## 가정
- 이 규칙은 리뷰어(LLM)가 따를 것을 기대하는 프롬프트 수준의 장치다. 하네스는 지적이 증분 diff 안에 있는지 검사하지 않는다.
- 첫 라운드에서 놓친 정확성 문제가 재작업 라운드에서 Follow-up으로만 남을 수 있다. 그 위험은 구현 PR 본문의 "후속 과제 (리뷰)" 절을 사람이 머지 전에 읽어 보는 것으로 막는다.
- 이 변경은 main 체크아웃의 하네스에 적용되므로 머지 뒤 `run`하는 작업부터 효과가 있다. 진행 중인 `harness-parallel`(round 7)이 첫 사용 사례다.
- "조작·동시성은 후속" 규칙은 완료 조건에 직접 적힌 시나리오를 예외로 둔다. 그래서 명세 작성자가 꼭 막아야 하는 경쟁 조건은 "완료 조건"에 적으면 차단으로 다뤄진다.

## 열린 질문
없음
