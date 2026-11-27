# Claude Code와 Codex 협업 운영안

관련 문서 · [클래식 음악 서비스 기획안 v0.1](service-plan-v0.1.md)

개발 프로젝트 기준이라면 **Claude Code와 ChatGPT Codex를 동일한 Git 저장소에 연결하되, 작업 공간과 역할을 분리하고 프로젝트 컨텍스트를 공유하는 구조**가 가장 이상적이라고 봄.

단순히 두 AI에게 동시에 코드를 작성시키는 것보다, 서로의 결과물을 검증하고 독립적으로 작업할 수 있도록 **Multi-Agent Harness**를 구성하는 방식이다. AI 두 마리를 고용해 놓고 같은 파일을 동시에 수정하게 하면 생산성이 아니라 충돌만 두 배가 된다.

## **1. 권장 아키텍처**

핵심은 모델에 종속된 개발 환경이 아니라, **프로젝트 자체에 종속된 개발 환경**을 만드는 것이다. Claude를 종료하고 Codex를 실행해도 작업을 이어갈 수 있어야 한다.

## **2. 협업 패턴**

| 패턴     | Claude   | Codex       | 추천도        |
| ------ | -------- | ----------- | ---------- |
| 교차 검증  | 구현       | 코드 리뷰       | 매우 높음      |
| 병렬 개발  | 기능 A 구현  | 기능 B 구현     | 매우 높음      |
| 설계 검증  | 아키텍처 설계  | 설계 비판 및 검증  | 매우 높음      |
| 테스트 분리 | 비즈니스 로직  | 독립적인 테스트 작성 | 높음         |
| 경쟁 구현  | 해결책 A    | 해결책 B       | 복잡한 문제에 한정 |
| 공동 수정  | 동일 파일 수정 | 동일 파일 수정    | 비추천        |

서로 다른 작업 ID는 병렬로 `run`할 수 있다. 같은 작업은 잠금 파일(`.harness/locks/<작업 ID>.json`)로 중복 실행이 거부된다.

Claude는 무조건 설계, Codex는 무조건 구현이라는 식으로 역할을 고정할 필요는 없다. **작업 단위로 Implementer와 Reviewer를 교대**시키는 것이 좋다.

## **3. 프로젝트 컨텍스트 통합**

두 모델의 대화 기록 대신 Git 저장소를 공통 기억으로 사용한다.

```
project/
├── AGENTS.md
├── CLAUDE.md
├── .claude/
├── .codex/
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── CONVENTIONS.md
│   ├── adr/
│   └── tasks/
├── harness/
│   ├── orchestrator.py
│   ├── prompts/
│   └── schemas/
├── scripts/
│   └── verify.sh
└── src/
```

| 파일                | 역할              |
| ----------------- | --------------- |
| `AGENTS.md`       | 모든 AI의 공통 행동 규칙 |
| `CLAUDE.md`       | Claude 전용 추가 지침 |
| `PRD.md`          | 프로젝트 요구사항       |
| `ARCHITECTURE.md` | 시스템 구조 및 기술 스택  |
| `adr/`            | 아키텍처 의사결정 기록    |
| `tasks/`          | 작업 명세 및 인수인계    |
| `verify.sh`       | 공통 검증 명령어       |

### **AGENTS.md 통합**

Codex는 `AGENTS.md`를 기본적으로 읽는다. 최신 Claude Code도 이를 지원하며, 기존 버전과의 호환성을 고려하면 `CLAUDE.md`에서 가져오는 방식도 좋다.





**CLAUDE.md**

```
@AGENTS.md

## Claude-specific instructions
```

이렇게 하면 공통 규칙을 두 번 관리할 필요가 없다.

**AGENTS.md 예시**

```
# Project Instructions

## Context
- Read docs/PRD.md
- Read docs/ARCHITECTURE.md
- Read the assigned task specification

## Development Rules
- Work only within the assigned scope.
- Never modify another agent's worktree.
- Do not change public interfaces without approval.
- Run tests before submitting changes.
- Record architectural decisions in docs/adr/.

## Definition of Done
- Acceptance criteria satisfied
- Build successful
- Tests passed
- Changes documented
- Ready for independent review
```

## **4. Git Worktree 기반 병렬 개발**

Git Worktree를 사용하면 동일한 저장소의 서로 다른 브랜치를 별도의 디렉터리에서 작업할 수 있다. Codex도 자체 Worktree 기능을 지원한다.


ChatGPT Learn



```
git worktree add ../project-claude -b agent/claude
git worktree add ../project-codex -b agent/codex
```

터미널 1:

```
cd ../project-claude
claude
```

터미널 2:

```
cd ../project-codex
codex
```

파일 수정 충돌은 격리할 수 있다. 다만 Merge Conflict, 개발 서버 포트, 로컬 DB, Docker 컨테이너 등의 공유 자원은 별도로 관리해야 한다.

## **5. 이상적인 개발 라이프사이클**

**01**

**Requirement**

Human · 요구사항 및 완료 조건 정의

**02**

**Plan**

Claude · 구현 계획 작성

**03**

**Challenge**

Codex · 설계 오류, 누락, 위험 요소 검토

**04**

**Implement**

Claude / Codex · 독립적인 작업 병렬 실행

**05**

**Cross Review**

상대 에이전트의 변경사항 검증

**06**

**Verify**

CI · Build, Test, Lint, Security Scan

**07**

**Merge**

Human · 최종 승인

중요한 것은 AI의 의견이 아니라 검증 가능한 결과다. 두 모델이 모두 코드가 완벽하다고 주장해도 테스트가 실패하면 실패한 코드다.

## **6. Harness를 통한 자동화**

매번 두 터미널에 프롬프트를 복사하는 것도 결국 사람이 병목이 되는 구조다.

두 CLI 모두 비대화형 실행이 가능하므로, Python 기반 Orchestrator에서 제어할 수 있다.





```
claude -p "작업 명세를 기반으로 구현 계획 작성"
```

```
codex exec "구현 계획을 검토하고 문제점 분석"
```

Harness가 담당해야 할 기능은 다음과 같다.

| 컴포넌트             | 역할                    |
| ---------------- | --------------------- |
| Agent Adapter    | Claude / Codex 실행 추상화 |
| Task Scheduler   | 작업 의존성 및 병렬 처리        |
| Context Manager  | 프로젝트 컨텍스트 관리          |
| Worktree Manager | 작업 공간 생성 및 격리         |
| Review Engine    | 에이전트 간 교차 검증          |
| State Manager    | 진행 상태 및 실패 복구         |
| Quality Gate     | 빌드, 테스트, 승인 관리        |

작업 상태는 명시적인 State Machine으로 관리한다.

작업 명세 → 독립 작업 공간에서 구현 → 교차 리뷰 → CI 검증

무한 리뷰 루프를 방지하기 위해 최대 재시도 횟수, 실행 시간, 토큰 사용량, 사람의 승인 조건도 설정해야 한다.

## **7. 활용 가능한 기술 스택**

| 목적              | 추천 기술                             |
| --------------- | --------------------------------- |
| Agent Runtime   | Claude Code + Codex CLI           |
| Orchestration   | Python asyncio                    |
| Workflow Engine | 직접 구현 또는 LangGraph                |
| 작업 격리           | Git Worktree                      |
| 상태 저장           | git 커밋 트레일러 + 잠금 파일                |
| 작업 명세 관리        | GitHub Issues / GitLab Work Items |
| 공통 컨텍스트         | AGENTS.md + Markdown              |
| 외부 도구 연결        | MCP                               |
| 결과 검증           | GitHub Actions / GitLab CI        |
| 실행 모니터링         | JSONL + 구조화된 로그                   |

MCP는 외부 도구와 데이터에 접근하는 수단이고, 에이전트 간 작업 분배와 상태 관리까지 해결해 주는 것은 아니다. 그 부분은 Harness에서 담당해야 한다.

## **8. 단계별 도입 추천**

**Level 1. Manual Collaboration**

AGENTS.md + Git Worktree + 교차 리뷰

별도 개발 없이 바로 적용.

**Level 2. Semi-Automated Harness**

Python + CLI + 작업 상태 관리

작업 분배, 리뷰 요청, 검증 자동화.

### Level 2 실행 방법

저장소 루트에서 Python 3.10 이상과 Git, GitHub CLI(`gh`)를 사용한다. `gh`는 한 번 설치하고 `gh auth login` 한다.
에이전트 단계를 실행하려면 `claude`, `codex` CLI가 PATH에 있어야 하며 각각 인증되어 있어야 한다.
Windows의 Claude Code 기본 설치 경로(`%USERPROFILE%\.local\bin\claude.exe`)도 자동으로 확인한다.
Windows Codex Desktop에서 하네스를 실행할 때는 `npm install -g @openai/codex`로
독립 Codex CLI를 설치한다. 하네스는 PATH 또는 기본 npm 전역 설치 경로에서
`codex.cmd`를 찾아 실행한다.
사람이 하는 일은 **명세 작성(에이전트와 대화)** 과 **GitHub PR 머지** 둘뿐이다. 하네스 상태는 로컬 DB가 아니라
`harness/<작업 ID>` 브랜치의 커밋 트레일러에 남는다.

1. 에이전트가 사용자와 대화하며 `docs/tasks/<작업 ID>.md`를 쓴다. `spec` 명령으로 초안을 만들 수도 있다.
2. 에이전트가 `propose <작업 ID>`를 실행한다. `origin/main` 위에 명세 파일 하나만 추가한 커밋을 `spec/<작업 ID>`로 push하고 명세 PR을 연다.
3. **사람이 명세 PR을 머지한다. 이것이 승인이다.**
4. 에이전트가 `run <작업 ID> <claude|codex>`를 실행한다. implement → review → (재작업) → verify를 진행하고 단계마다 커밋과 push를 하며, 통과하면 구현 PR을 연다.
5. **사람이 구현 PR을 머지한다.**

```powershell
python -m harness.orchestrator spec add-tests "업로드 이미지 크기를 10MB로 제한하고 싶다" claude
python -m harness.orchestrator propose add-tests
python -m harness.orchestrator run add-tests codex --max-rounds 3 --wait 600
python -m harness.orchestrator status add-tests
```

`spec`은 `harness/prompts/spec.md` 프롬프트에 따라 읽기 전용 에이전트(Claude는 편집·Bash 도구 차단, Codex는 `read-only` 샌드박스)가
`docs/tasks/<작업 ID>.md`에 목표·범위·동작 명세·완료 조건·검증 명령·가정·열린 질문을 쓰게 하고, 저장소에 변경이 생기면 실패한다.
채팅에서 직접 요청해도 AGENTS.md의 같은 규칙에 따라 에이전트가 명세를 먼저 쓴다.

- `propose`는 main 체크아웃의 명세(커밋 안 된 파일 가능)를 읽는다. "열린 질문" 절이 정확히 `없음`이 아니면 거부한다.
  main 체크아웃의 브랜치·인덱스는 바꾸지 않는다. push와 PR 생성이 성공하고 main 체크아웃의 명세가 git에서 추적되지 않는 파일이며
  내용이 push한 것과 같으면, 머지 뒤 `git pull`을 막지 않도록 그 로컬 사본을 지운다. 추적 중이거나 내용이 다르거나 push·PR 생성이 실패하면 남긴다. 비교 전에 파일을 같은 폴더의 임시 이름으로 옮겨 확인한 바이트만 지우므로, 그 사이 편집기가 원래 경로에 새로 저장한 파일은 지우지 않는다.
  `git ls-files`가 실패하는 등 추적 여부를 git으로 확인하지 못해도 남긴다.
  파일이 잠겨 지우지 못하면(Windows) 남겨 두었다고 출력하고, 이미 성공한 `propose`는 실패로 바꾸지 않는다.
  머지 전에 명세를 고치려면 `git show origin/spec/<작업 ID>:docs/tasks/<작업 ID>.md > docs/tasks/<작업 ID>.md`로 되살려 고친 뒤 다시 `propose`하면 `spec/<작업 ID>`가 갱신된다.
  Windows PowerShell 5.1의 `>`는 UTF-16으로 저장하므로, 그 환경에서는 `git restore --source=origin/spec/<작업 ID> --worktree -- docs/tasks/<작업 ID>.md`로 되살린다(인덱스는 바꾸지 않는다).
  `gh`가 없거나 인증되지 않았으면 push까지 하고 수동 PR URL을 안내한다(로컬 사본은 남는다).
- `run`은 `origin/main`에 명세가 있어야 시작한다. 없으면 종료 코드 3이며, `--wait SECONDS`를 주면 30초마다 확인하며 머지를 기다린다.
  명세 내용과 "검증 명령" 절의 명령(첫 코드 블록, 없으면 절 본문 첫 줄)은 `origin/main` 기준이다.
  `harness/<작업 ID>` 브랜치와 `.harness/worktrees/<작업 ID>` worktree를 `origin/main`에서 만들고, 이미 있으면 이어서 진행한다.
- 단계는 브랜치에서 `origin/main` 이후 `Harness-Step` 트레일러가 있는 마지막 커밋으로 계산한다. 중간에 멈췄다면 같은 명령을 다시 실행한다.
  트레일러 없는 커밋이 끼어 있거나 worktree에 커밋 안 된 변경이 있으면 오류로 멈춘다.
- 구현 에이전트가 쓸 수 없는 파일(예: `.claude/settings.json`)은 사람이 `harness/<작업 ID>` 브랜치에 직접 커밋한 뒤
  `run <작업 ID> <claude|codex> --adopt`로 이어받는다. 잠금과 원격 동기화 뒤, 마지막 하네스 커밋(없으면 `origin/main`) 뒤의
  트레일러 없는 커밋을 하네스 작성자의 빈 기록 커밋 하나로 새 implement 라운드에 편입한다.
  ```
  harness(<작업 ID>): adopt human commits

  <이어받은 커밋마다 "<짧은 SHA> <작성자 이름> <제목>">

  Harness-Task: <작업 ID>
  Harness-Step: implement
  Harness-Agent: human
  Harness-Round: <이전 최대 round + 1, 하네스 커밋이 없으면 1>
  Harness-Adopted: <이어받은 첫 커밋 SHA>..<이어받은 마지막 커밋 SHA>
  ```
  기록 커밋을 push한 뒤 review → verify → 구현 PR로 이어진다. 리뷰어는 `run`에 준 에이전트의 반대쪽이다.
  기록 커밋은 트리를 바꾸지 않으므로 리뷰가 승인하고 verify가 검증하는 트리에 사람의 변경이 포함되며, CI 게이트는 바뀌지 않는다.
  이어받기는 `--max-rounds`에 세지 않는다. 이어받을 커밋이 없으면 `--adopt`는 아무것도 하지 않는다.
  다음 경우에는 기록 커밋을 만들지 않고 종료 코드 1로 멈춘다: 머지 커밋이 있다, 승인된 명세 `docs/tasks/<작업 ID>.md`를 수정한다,
  트레일러 없는 커밋 사이에 하네스 커밋이 끼어 있다(연속 구간이 아니다), 되돌림 등으로 브랜치 트리가 `origin/main`과 같다(`이어받을 변경이 없습니다`).
  사람 커밋끼리 서로 되돌려도 브랜치에 `origin/main` 대비 변경이 남아 있으면 이어받는다. 본문 목록은 8000자 제한 없이 커밋마다 한 줄을 모두 남긴다.
  작성자는 검증하지 않으므로 사람이 PR에서 본문 목록의 작성자를 확인한다. `--adopt` 없이 트레일러 없는 커밋이 있으면 지금처럼 거부하고 `--adopt` 안내를 덧붙인다.
- 모든 하네스 커밋의 작성자는 `harness <harness@example.invalid>`이다. implement는 에이전트의 최종 응답, review는 리뷰어 출력,
  verify는 검증 명령 출력의 마지막 100줄을 본문(최대 8000자)에 남긴다. 에이전트 원본 로그는 `.harness/logs/<작업 ID>/`(로컬)에만 있다.
  Claude 구현자는 `python -m unittest`와 Gradle(`gradle`, `gradlew`, `backend/gradlew` 및 `.bat` 형태) 명령만 실행할 수 있다(review·spec은 읽기 전용).
  허용 규칙은 하나의 명령 접두어 목록(`IMPLEMENT_COMMAND_PREFIXES`)에서 Bash와 PowerShell 도구 양쪽으로 만들고, PowerShell에는
  `.\gradlew.bat`, `.\backend\gradlew.bat`, `backend\gradlew.bat`를 더 허용한다. Claude implement 프롬프트는 이 접두어로 시작하는 단일 명령을
  worktree 루트에서 실행하라고 안내한다. `cd`, `&&`, `;`, `|`, 리디렉션, 임시 스크립트는 승인이 필요해 거부되며,
  테스트를 못 돌렸으면 최종 응답에 그 사실과 이유를 쓰게 한다.
  프롬프트는 이 명령을 Bash 도구로 먼저 실행하고, 한 도구가 거부하면 다른 도구로 같은 명령을 다시 시도하라고 안내한다.
  확인 결과(Windows 11, Windows PowerShell 5.1, `harness-windows-tools` implement round 3): 하네스가 띄운 세션에서
  `.claude/settings*.json`에 허용 규칙이 없는데도 Bash의 `python -m unittest discover -s tests`(81개 통과)와 `backend/gradlew.bat --version`은
  승인 없이 실행됐다. 따라서 `--allowedTools`는 세션에 전달된다. 같은 세션의 PowerShell 도구는 `python -m unittest discover -s tests`,
  `backend/gradlew.bat --version`, `.\backend\gradlew.bat --version`을 모두 "contains multiple operations"로 거부했다.
  단일 명령도 거부되므로 규칙이 적용되기 전에 Claude Code의 PowerShell 명령 분석 단계에서 막히는 것으로 보이며, 하네스 쪽 규칙으로는 풀 수 없다.
  PowerShell 규칙은 이 분석이 고쳐지면 바로 쓰이도록 남겨 두고, 지금은 Bash 도구가 실제 실행 경로다.
  이 안내는 Claude의 도구 권한에 관한 것이므로 Codex 구현자 프롬프트에는 넣지 않는다.
  Codex 샌드박스는 네트워크가 닫혀 있으므로 Gradle이 필요한 작업은 Claude를 구현자로 지정한다.
  검증 명령 첫 인자에 경로 구분자가 있는 상대 경로(예: `backend/gradlew.bat`)를 쓰면 작업 worktree 기준으로 실행 파일을 찾는다.
- review는 상대 에이전트에 명세와 `origin/main`부터 작업 HEAD까지의 diff를 전달한다. 리뷰어는 지적을 두 심각도로 나눈다.
  - 차단(Blocking): 근거(파일 위치와 재현 시나리오)가 있고, 명세의 동작 명세·완료 조건 위반, 일반적인 사용 흐름의 잘못된 결과·데이터 손실·크래시,
    가드·승인·게이트 같은 보안·권한 장치의 우회·약화, 테스트 실패·기존 테스트 파손 중 하나인 지적.
  - 후속(Follow-up): 그 밖의 모든 지적(명세가 요구하지 않은 드문 경계 상황, 방어 코드, 리팩터링, 이름·문서·스타일, 범위 밖 개선). 확신이 없으면 후속이다.
    재현하려면 작업자가 설정·로그·다른 세션의 파일을 일부러 조작해야 하거나 두 프로세스가 같은 순간에 같은 지점을 통과해야 하는 시나리오도,
    명세의 "완료 조건"에 그 시나리오가 직접 적혀 있지 않은 한 후속이다. 꼭 막아야 하는 경쟁 조건은 완료 조건에 적는다.
- 재작업 라운드(브랜치에 이전 review 커밋이 있을 때)에는 리뷰 입력 끝에 두 절이 더 붙는다.
  - `Previous blocking findings`: 직전 review 커밋 본문의 `## Blocking` 절. 직전 리뷰가 APPROVE였거나 절이 없으면 `None`.
  - `Changes since the previous review`: 직전 리뷰의 `Harness-Reviewed` 커밋부터 HEAD까지의 diff. 그 커밋이 현재 히스토리에 없으면
    `Not available; review the full diff above.`
  이때 차단은 직전 차단 지적이 아직 해결되지 않았거나, `Changes since the previous review`의 변경이 새로 만든 회귀·명세 위반이거나,
  명세의 완료 조건이 충족되지 않은 경우로 좁혀진다. 그 밖의 지적(앞서 지적되지 않았고 증분 diff에도 없는 코드에서 새로 찾은 문제 포함)은 후속이다.
  첫 리뷰 라운드는 지금처럼 전체 diff만 보고 이 제한이 없다. 이 규칙은 리뷰어 프롬프트 수준의 장치이며 하네스가 지적 위치를 검사하지는 않으므로,
  재작업 라운드에서 후속으로 남은 정확성 문제는 사람이 구현 PR의 후속 과제 절에서 확인한다.
- 리뷰 출력은 `## Blocking`과 `## Follow-ups` 두 절을 쓰고(해당 없으면 본문 `None`), 마지막 두 줄을 정확히 다음처럼 끝낸다.
  ```
  BLOCKING: <차단 지적 수>
  VERDICT: <APPROVE|REQUEST_CHANGES>
  ```
  하네스는 끝의 빈 줄을 뺀 마지막 줄이 `VERDICT` 줄이고 바로 앞 줄이 `BLOCKING: <0 이상의 정수>`일 때만 판정을 낸다(사이에 빈 줄이 있어도 안 된다).
  `VERDICT: APPROVE` 한 줄만 쓰거나 형식이 다르면 `MISSING`이다. 판정은 수로 정한다: 0이면 `APPROVE`, 1 이상이면 `REQUEST_CHANGES`.
  `VERDICT` 줄이 수와 어긋나면 `리뷰 판정과 BLOCKING 수가 어긋나 BLOCKING 수를 따릅니다` 경고를 남기고 수를 따른다.
  review 커밋에는 `Harness-Blocking: <n>`(`MISSING`이면 `?`) 트레일러가 붙는다.
- 반려되면 이전 리뷰 커밋의 본문이 다음 implement 프롬프트에 들어가고, 구현자는 Blocking 항목만 고치며 후속 과제로 범위를 넓히지 않는다.
- 후속 과제는 승인을 막지 않는다. 마지막 APPROVE 리뷰의 `## Follow-ups` 절(하위 제목과 코드 블록 포함, 코드 블록 안의 `#` 줄은 제목으로 보지 않는다)이 `None`이 아니면 구현 PR 본문 끝에
  `## 후속 과제 (리뷰)` 절로 붙으므로, 사람이 PR에서 보고 별도 작업으로 다룰지 정한다.
- verify는 마지막 APPROVE 리뷰가 본 커밋과 HEAD의 트리가 같을 때만 실행한다. 실패해도 `Harness-Result: fail` 커밋을 남기고 종료 코드 1로 멈춘다.
  원인을 해결한 뒤 `run`을 다시 실행하면 verify부터 이어진다.
- 각 단계 뒤에 `git push origin harness/<작업 ID>`를 한다. 검증을 통과하면 구현 PR을 연다. 머지는 사람만 하며 하네스는 자동 머지를 켜지 않는다.
- `--max-rounds`(기본 3)는 이번 실행의 implement 횟수 상한이다. 상한까지 반려되면 멈추고 사람에게 넘긴다. 실행 제한은 기본 900초이며
  `--timeout 1800`처럼 하위 명령 앞에 지정한다.
- `status <작업 ID>`는 git에서 계산한 단계·round·마지막 판정, 브랜치와 push 여부, 구현 PR URL, worktree, 마지막 로컬 로그를 보여 준다.
  이어받은 라운드가 있으면 `adopted: <첫 SHA>..<마지막 SHA> (round <n>)` 줄을 더한다. 마지막 하네스 커밋 뒤에 트레일러 없는 커밋이 있으면
  오류로 멈추지 않고 다음 단계를 `blocked (...)`로 표시하며, 이전 이어받기 줄과 나머지 정보도 그대로 보여 준다.

### 여러 세션의 병렬 작업

한 PC에서 여러 Claude 세션이 이슈의 서로 다른 작업을 동시에 `이슈 → 명세 PR → 구현 PR`까지 처리할 수 있다. 어떤 이슈를 누가 집을지는 세션(사람)이 정한다. 하네스는 상주하지 않고 작업을 자동 분배하지 않는다. 의존 작업(머지 안 된 다른 작업을 전제하는 작업)은 그 작업이 머지된 뒤에 시작하고, 여러 PC·클론의 동시 작업은 범위 밖이다(락 파일은 한 PC의 같은 저장소 안에서만 서로 보인다).

- `from-issue <번호> <claude|codex> [--no-comment]`: `gh issue view`로 이슈를 읽어 작업 ID `issue-<번호>`의 명세 초안을 `docs/tasks/issue-<번호>.md`에 쓴다(`spec`과 같은 읽기 전용 에이전트, 이슈 본문은 데이터로만 취급). 이슈가 없거나 닫혀 있으면 종료 코드 1이다.
  쓰기 전에 선점을 검사한다. 로컬 `docs/tasks/issue-<번호>.md`가 있거나(같은 PC의 다른 세션), `origin`에 `spec/issue-<번호>`·`harness/issue-<번호>`가 있거나, `origin/main`에 그 명세가 있으면 아무것도 만들지 않고 이유를 출력한 뒤 종료 코드 4이다.
  명세의 "열린 질문"이 `없음`이 아니면 이슈에 코멘트로 남긴다(`--no-comment`로 끈다). 이슈를 닫거나 라벨·담당자를 바꾸지 않는다.
- `propose`가 확정 선점이다. 원격에 `spec/<작업 ID>`가 이미 있으면 push하지 않고 종료 코드 4로 거부한다. 내가 올린 명세를 고치는 것이면 `--update`로 `--force-with-lease` 갱신한다. 새 브랜치는 강제 push하지 않으므로 동시에 push하면 한쪽은 git이 거부하고 같은 안내(종료 코드 4)가 나온다.
- 작업 ID가 `issue-<번호>`면 명세 PR 본문 끝에 `Refs #<번호>`, 구현 PR 본문 끝에 `Closes #<번호>`가 붙는다.
- main 동기화: `run`은 잠금과 원격 동기화 뒤 단계를 계산하기 전에, 작업 브랜치가 `origin/main`보다 뒤처졌으면(`git merge-base --is-ancestor origin/main HEAD`가 거짓) main을 병합한다. `--no-sync`로 건너뛴다.
  하네스 커밋이 없으면 fast-forward만 한다. 있으면 병합 커밋(`harness(<id>): sync with main`, 트레일러 `Harness-Step: sync`, `Harness-Merged: <origin/main SHA>`)을 만들어 push한다. 트레일러가 가리키는 SHA가 바뀌지 않도록 rebase하지 않고 병합한다.
  충돌하면 충돌 표시가 든 채로 커밋하고 `Harness-Conflict: <파일 목록>`을 더한다. 다음 단계는 새 implement 라운드이며 프롬프트에 충돌 파일과 "표시를 모두 없애고 양쪽 의도를 보존하라, main 쪽 변경을 되돌리지 마라"가 들어간다. 그 뒤에도 표시가 남아 있으면(`Harness-Conflict`의 파일에 `<<<<<<<` 또는 `>>>>>>>`로 시작하는 줄이 하나라도 있으면. 표시 길이는 git 기본값 7로 고정하고 `.gitattributes`의 `conflict-marker-size`는 읽지 않는다. `=======`는 Markdown 제목 밑줄과 구별할 수 없어 판정에 쓰지 않으므로, 구분선만 남은 불완전한 해결은 코드면 verify가, 문서면 리뷰가 잡는다. 쉼표·따옴표가 든 경로는 `Harness-Conflict`에 큰따옴표로 감싸 적는다) 리뷰로 가지 않고 `충돌 표시가 남아 있습니다: <파일>` 오류(종료 코드 1)로 멈추며, 다시 `run` 하면 implement 라운드로 이어진다. 충돌 표시가 든 커밋은 verify pass가 아니므로 CI 게이트가 통과시키지 않는다.
  충돌 없는 병합은 review부터 다시 거친다. `done` 작업이 뒤처졌으면 동기화 → review → verify를 다시 하고 열린 PR이 갱신된다. 동기화는 `--max-rounds`에 세지 않고, 충돌 해결 implement는 센다.
- `git fetch`와 `git worktree add`는 다른 세션이 저장소 락(`index.lock`, `cannot lock ref` 등)을 잡고 있어 실패하면 2초 간격으로 최대 3번 시도한다. 다른 오류는 재시도하지 않는다.
- `status`는 작업 브랜치가 `origin/main`보다 뒤처졌으면 `behind main: <n> commits` 줄을 더한다.

### 구독 한도에 따른 자동 배정

`spec`과 `run`의 에이전트 자리에 `auto`를 지정할 수 있다. 하네스는 요청 또는 승인된 명세의 목표·동작 명세에서 문서 반영, 일반 구현, 복구·상태 전이 작업을 구분하고 CLI가 보고한 모델과 추론 수준을 확인한다. Codex는 ChatGPT App Server, Claude는 같은 CLI의 모델 목록과 영문 `//usage` 출력을 사용한다. 각 후보의 적용 구간 중 가장 낮은 잔여율을 비교하고, 동률이면 Codex를 먼저 선택한다.

`run`은 구현자와 상대 리뷰어의 한도를 모두 확인해야 시작한다. 관측 유효기간은 5분이다. 한도가 소진되면 초기화 후 같은 명령을 다시 실행해 재조회한다. 수동 배정은 `run <작업 ID> codex` 또는 `run <작업 ID> claude`로 실행한다. 리뷰는 재개 시에도 구현 커밋의 제공자를 기준으로 배정한다. 실행 중 한도로 멈춘 자동 구현의 부분 변경은 해당 시도의 로그 옆에 바이너리 변경을 포함한 `.patch` 파일로 보관한다. 재개는 마지막 완료 단계에서 시작하며 부분 변경은 `git apply`로 복원할 수 있다.

자동 실행은 단계 로그 옆의 JSON 파일에 모델, 추론 수준, 잔여율, 관측·초기화 시각(Unix 초), 소요 시간 및 보고된 토큰 항목을 남긴다. 검증 기록에는 첫 검증 통과 여부, 리뷰 반려 횟수, 모든 로컬 작업에서 같은 작업 유형·제공자·단계별로 집계한 시도 합계가 들어간다. 캐시와 추론 토큰은 개별 항목으로 유지하며 누락 값은 `null`이다. 해결하지 못한 코드 문제와 시도한 분석을 각각 `UNRESOLVED:`와 `EVIDENCE:` 줄에 남기면 다음 시도에서 해당 단계의 설정을 한 번 높인다.

### 잠금

단계를 실행하는 동안 `.harness/locks/<작업 ID>.json`(`pid`, `step`, `started`)을 배타적으로 만들고 끝나면 지운다.
파일이 있고 pid가 살아 있으면 `이미 실행 중` 오류(종료 코드 1)이다. pid가 죽었으면 하네스가 파일을 지우고 진행한다.
`run`은 HEAD를 움직일 수 있는 일(원격 동기화, push, 단계 계산)을 하기 전에 잠금을 얻는다. 잠금은 `step: plan`으로 만들고, 단계를 정한 뒤 같은 잠금 파일의 `step`을 그 단계로 원자적으로 바꾼다. 그래서 동시에 실행한 다른 프로세스가 단계 도중의 worktree를 움직이거나 이미 진행한 단계를 중복하지 않는다.

잠금을 얻은 뒤, 단계를 계산하기 전에 `git fetch origin harness/<작업 ID>`로 원격과 맞춘다. 로컬이 원격의 조상이고 worktree가 깨끗하면 원격으로 fast-forward하고(다른 클론이 이미 기록한 단계를 다시 실행하지 않는다), 로컬에만 있는 커밋은 단계 계산(트레일러 검사)을 통과한 뒤 push부터 한다. 둘이 갈라졌으면 `로컬 harness/<작업 ID>와 origin/harness/<작업 ID>가 갈라졌습니다` 오류(종료 코드 1)로 에이전트 실행 없이 멈춘다.

### 하네스 강제 장치

AGENTS.md의 규칙은 권고가 아니라 다음 장치로 강제한다.

| 장치 | 위치 | 막는 것 |
| --- | --- | --- |
| 편집 가드 훅 | `.claude/settings.json` → main 체크아웃의 `harness/guard.py` (`git rev-parse --git-common-dir`의 부모에서 찾으며, worktree의 사본은 쓰지 않고 못 찾으면 거부) | Claude의 main 체크아웃 편집(`docs/tasks/*.md` 제외), `.harness/` 편집, 잠금 파일이 implement를 가리키지 않는 worktree 편집 |
| Bash·PowerShell 가드 | 같은 훅 (`Bash`와 `PowerShell` 도구 이벤트를 같은 명령 문자열 검사로 처리) | Claude의 `gh pr merge`, PR 승인 리뷰, `.harness/locks` 수정, `harness-maintenance`를 담은 `gh pr edit`/`gh pr create`/`gh label`/`gh api` |
| 읽기 전용 spec | `harness/orchestrator.py` | spec 단계 에이전트의 파일 수정 |
| 명세 PR 머지 | `propose` → `run` | 사람이 머지하지 않은 명세의 구현(`origin/main`에 명세가 없으면 `run`이 거부) |
| pre-commit 훅 | `.githooks/pre-commit` | `main`/`master` 직접 커밋(충돌 해결 머지 커밋은 허용) |
| CI 게이트 | `.github/workflows/harness-gate.yml` → `harness/gate.py` | 커밋 트레일러로 확인: `spec/<작업 ID>` PR은 명세 파일 추가 하나뿐이어야 하며 base에 같은 명세가 이미 있으면 실패하고, `harness/<작업 ID>` PR은 승인된 명세를 수정하지 않았으며 HEAD가 통과한 verify 커밋이고 검증한 트리를 APPROVE 리뷰가 승인했어야 한다. 그 밖의 브랜치는 `harness-maintenance` 라벨이 없으면 실패. 하네스 테스트도 실행 |

클론마다 한 번 git 훅을 켠다.

```powershell
git config core.hooksPath .githooks
```

GitHub 저장소 설정에서 main 브랜치 보호 규칙을 켜고 `harness-gate`를 필수 상태 검사로 지정해야 CI 게이트가 머지를 실제로 막는다.

하네스 자체를 유지보수할 때는 에이전트를 띄우는 셸에서 `HARNESS_GUARD=off`를 설정한다(PowerShell: `$env:HARNESS_GUARD='off'`). PR에는 `harness-maintenance` 라벨을 붙인다. 라벨 부여는 사람만 한다. 에이전트가 라벨을 붙이는 명령은 Bash 가드가 거부하지만 문자열 검사라 완전하지 않으므로, 사람이 PR에서 라벨을 확인하는 것이 최종 방어선이다. 라벨 권한 제한은 GitHub 저장소 설정에서 사람이 한다.

한계: Bash·PowerShell 가드는 명령 문자열만 검사하므로 우회할 수 있고, Bash로 쓰는 일반 파일은 막지 못한다. Codex 대화형 세션도 훅으로 막지 않는다.
커밋 트레일러는 서명되지 않아 쓰기 권한이 있으면 위조할 수 있다. 최종 방어선은 사람의 PR 검토와 머지, pre-commit 훅, CI 게이트이다.

**Level 3. Multi-Agent Orchestration**

Scheduler + State Machine + CI/CD

의존성 기반 병렬 실행, 실패 복구, 자동 검증.

**Level 4. Model-Agnostic Harness**

Claude + Codex + Gemini + 기타 모델

작업 특성, 성능, 비용에 따른 동적 모델 선택.

## **결론**

이 프로젝트의 도입안으로는 처음부터 거대한 에이전트 프레임워크를 도입하기보다 **Level 2를 구축하고 Level 3으로 확장하는 방향**을 추천한다.

다만 위 설계는 로컬 Claude Code와 Codex CLI를 사용할 수 있다는 전제이며, 실제 구독 한도와 실행 권한, 자동화 정책은 별도로 확인해야 한다.

궁극적으로 지향할 구조는 다음과 같다.

- **Human:** Product Owner
- **Harness:** Engineering Manager
- **Claude / Codex / Gemini:** 교체 가능한 Worker
- **Git:** Shared Memory
- **CI/CD:** Quality Gate
- **Issue Tracker:** Task Queue

모델은 계속 바뀌겠지만 개발 절차와 검증 체계는 유지된다. 특정 AI의 성능에 의존하는 개발 방식보다, 어떤 AI가 들어와도 일정 수준 이상의 결과를 만들어 내는 **Harness Engineering**이 장기적으로 더 가치 있다.
