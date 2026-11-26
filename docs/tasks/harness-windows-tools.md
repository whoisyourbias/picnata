# implement 단계에서 테스트·빌드 명령을 확실히 실행할 수 있게 하기

## 목표
Windows에서 implement 단계의 Claude가 허용된 테스트·빌드 명령(`python -m unittest`, Gradle)을 매번 실행할 수 있게 한다. 구현자가 테스트를 돌려 본 뒤 커밋하게 만든다. 함께 `propose` 뒤 로컬 명세 사본이 남아 `git pull`이 막히는 문제를 없앤다.

## 범위
- 포함
  - Claude implement 허용 도구에 PowerShell 도구용 규칙을 Bash 규칙과 같은 명령 집합으로 추가
  - implement 프롬프트에 허용된 명령 형태와 금지 형태(명령 연결, 파이프, 임시 스크립트)를 명시
  - `propose`가 push에 성공하면 main 체크아웃의 커밋 안 된 명세 사본을 지운다
  - 테스트, `docs/agent-collaboration.md` 갱신
- 제외
  - review 단계(Claude `plan` 모드, Codex `read-only` 샌드박스) 권한 변경. 리뷰어가 테스트를 못 돌리는 문제는 다루지 않는다 (verify가 실제 테스트를 맡는다)
  - Codex implement 권한 변경
  - 허용 명령 집합 자체를 늘리는 것 (Python unittest와 Gradle만 유지)
  - 허용 명령을 설정 파일로 빼는 일반화

## 변경 대상
- `harness/orchestrator.py`: `CLAUDE_IMPLEMENT_ALLOWED_TOOLS`, implement 프롬프트(`Task.implement`), `propose`
- `tests/test_harness.py`
- `docs/agent-collaboration.md`

## 동작 명세

### 허용 도구
- 지금의 Bash 규칙 9개(`python -m unittest`, `python3 -m unittest`, `gradle`, `./gradlew`, `gradlew`, `gradlew.bat`, `backend/gradlew`, `backend/gradlew.bat`, `./backend/gradlew`)는 그대로 둔다.
- 같은 9개 명령 접두어를 `PowerShell(<명령>:*)` 형태로 추가한다. 추가로 PowerShell에서 쓰는 `.\gradlew.bat`, `.\backend\gradlew.bat`, `backend\gradlew.bat` 접두어도 `PowerShell(...)`로 허용한다.
- 두 목록은 하나의 명령 접두어 목록에서 생성해 어긋나지 않게 한다.

### implement 프롬프트
기존 문장 뒤에 다음 내용을 덧붙인다 (영어 프롬프트에 맞춰 영어로 작성).
- 허용된 명령 접두어 목록 전체.
- 테스트·빌드는 worktree 루트에서 그 접두어로 시작하는 단일 명령으로 실행한다. `cd`, `&&`, `;`, `|`, 리디렉션, 임시 스크립트 실행은 승인이 필요해 거부된다.
- 예: `python -m unittest discover -s tests`, `python -m unittest tests.test_gate`, `backend/gradlew.bat -p backend test`.
- 테스트를 실행하지 못했으면 최종 응답에 그 사실과 이유를 쓴다.

### `propose` 뒤 로컬 사본 정리
- `spec/<id>` push가 성공하고, main 체크아웃의 `docs/tasks/<id>.md`가 git에서 추적되지 않는 파일이며, 내용이 push한 blob과 같으면 그 파일을 지운다.
- 출력에 `로컬 사본을 지웠습니다. 수정하려면: git show origin/spec/<id>:docs/tasks/<id>.md > docs/tasks/<id>.md` 안내를 추가한다.
- push나 PR 생성이 실패하면 지우지 않는다. 파일이 추적 중이거나 내용이 다르면 지우지 않는다.

## 완료 조건
- [ ] Claude implement 명령의 `--allowedTools`에 기존 Bash 규칙 9개와 PowerShell 규칙 12개가 모두 있다는 테스트.
- [ ] Bash 규칙과 PowerShell 규칙이 같은 접두어 목록에서 나온다는 테스트 (PowerShell 전용 3개 제외 시 접두어 집합이 같다).
- [ ] implement 프롬프트에 허용 접두어 전부와 "single command" 안내가 들어간다는 테스트.
- [ ] review·spec 명령과 Codex implement 명령이 바뀌지 않았다는 기존 테스트가 통과한다.
- [ ] `propose` 성공 시 같은 내용의 추적 안 된 사본이 지워지고, 실패 시·내용이 다를 때·추적 중일 때는 남는다는 테스트.
- [ ] 기존 테스트 전부 통과.

## 검증 명령
```
python -m unittest discover -s tests
```

## 가정
- Claude Code가 Windows에서 PowerShell 도구를 쓰고, 권한 규칙 `PowerShell(<접두어>:*)`를 Bash 규칙과 같은 방식으로 해석한다. 이 작업의 implement 로그에서 PowerShell 규칙으로 테스트가 실행됐는지 확인해 PR에 적는다.
- `harness-hardening` implement 로그에서 거부된 명령은 명령 연결, PowerShell 도구, 임시 스크립트 실행이었다. 같은 라운드에서도 단일 `python -m unittest` 명령은 실행됐다.
- `propose` 뒤 명세를 고치는 일은 드물다. 필요하면 원격 브랜치에서 되살린다.

## 열린 질문
없음
