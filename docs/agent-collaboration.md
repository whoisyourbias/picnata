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
  main 체크아웃의 브랜치·인덱스·작업 트리는 바꾸지 않는다. 머지 전에 명세를 고쳤다면 다시 `propose`하면 `spec/<작업 ID>`가 갱신된다.
  `gh`가 없거나 인증되지 않았으면 push까지 하고 수동 PR URL을 안내한다.
- `run`은 `origin/main`에 명세가 있어야 시작한다. 없으면 종료 코드 3이며, `--wait SECONDS`를 주면 30초마다 확인하며 머지를 기다린다.
  명세 내용과 "검증 명령" 절의 명령(첫 코드 블록, 없으면 절 본문 첫 줄)은 `origin/main` 기준이다.
  `harness/<작업 ID>` 브랜치와 `.harness/worktrees/<작업 ID>` worktree를 `origin/main`에서 만들고, 이미 있으면 이어서 진행한다.
- 단계는 브랜치에서 `origin/main` 이후 `Harness-Step` 트레일러가 있는 마지막 커밋으로 계산한다. 중간에 멈췄다면 같은 명령을 다시 실행한다.
  트레일러 없는 커밋이 끼어 있거나 worktree에 커밋 안 된 변경이 있으면 오류로 멈춘다.
- 모든 하네스 커밋의 작성자는 `harness <harness@example.invalid>`이다. implement는 에이전트의 최종 응답, review는 리뷰어 출력,
  verify는 검증 명령 출력의 마지막 100줄을 본문(최대 8000자)에 남긴다. 에이전트 원본 로그는 `.harness/logs/<작업 ID>/`(로컬)에만 있다.
  Claude 구현자는 `python -m unittest`와 Gradle(`gradle`, `gradlew`, `backend/gradlew` 및 `.bat` 형태) 명령만 실행할 수 있다(review·spec은 읽기 전용).
  Codex 샌드박스는 네트워크가 닫혀 있으므로 Gradle이 필요한 작업은 Claude를 구현자로 지정한다.
  검증 명령 첫 인자에 경로 구분자가 있는 상대 경로(예: `backend/gradlew.bat`)를 쓰면 작업 worktree 기준으로 실행 파일을 찾는다.
- review는 상대 에이전트에 명세와 `origin/main`부터 작업 HEAD까지의 diff를 전달한다. 리뷰어는 출력 마지막 줄을
  `VERDICT: APPROVE` 또는 `VERDICT: REQUEST_CHANGES`로 끝내야 하며, 응답의 마지막 비어 있지 않은 줄만 읽는다. 그 줄이 정확히 두 판정 중 하나가 아니면(본문 중간 인용 포함) `MISSING`으로 기록한다.
  반려되면 이전 리뷰 커밋의 본문이 다음 implement 프롬프트에 들어간다.
- verify는 마지막 APPROVE 리뷰가 본 커밋과 HEAD의 트리가 같을 때만 실행한다. 실패해도 `Harness-Result: fail` 커밋을 남기고 종료 코드 1로 멈춘다.
  원인을 해결한 뒤 `run`을 다시 실행하면 verify부터 이어진다.
- 각 단계 뒤에 `git push origin harness/<작업 ID>`를 한다. 검증을 통과하면 구현 PR을 연다. 머지는 사람만 하며 하네스는 자동 머지를 켜지 않는다.
- `--max-rounds`(기본 3)는 이번 실행의 implement 횟수 상한이다. 상한까지 반려되면 멈추고 사람에게 넘긴다. 실행 제한은 기본 900초이며
  `--timeout 1800`처럼 하위 명령 앞에 지정한다.
- `status <작업 ID>`는 git에서 계산한 단계·round·마지막 판정, 브랜치와 push 여부, 구현 PR URL, worktree, 마지막 로컬 로그를 보여 준다.

### 잠금

단계를 실행하는 동안 `.harness/locks/<작업 ID>.json`(`pid`, `step`, `started`)을 배타적으로 만들고 끝나면 지운다.
파일이 있고 pid가 살아 있으면 `이미 실행 중` 오류(종료 코드 1)이다. pid가 죽었으면 하네스가 파일을 지우고 진행한다.
`run`은 잠금을 얻은 뒤 단계를 다시 계산하므로, 동시에 실행한 다른 프로세스가 이미 진행한 단계를 중복하지 않는다.

단계를 계산하기 전에 `git fetch origin harness/<작업 ID>`로 원격과 맞춘다. 로컬이 원격의 조상이고 worktree가 깨끗하면 원격으로 fast-forward하고(다른 클론이 이미 기록한 단계를 다시 실행하지 않는다), 로컬에만 있는 커밋은 push부터 한다. 둘이 갈라졌으면 `로컬 harness/<작업 ID>와 origin/harness/<작업 ID>가 갈라졌습니다` 오류(종료 코드 1)로 에이전트 실행 없이 멈춘다.

### 하네스 강제 장치

AGENTS.md의 규칙은 권고가 아니라 다음 장치로 강제한다.

| 장치 | 위치 | 막는 것 |
| --- | --- | --- |
| 편집 가드 훅 | `.claude/settings.json` → main 체크아웃의 `harness/guard.py` (`git rev-parse --git-common-dir`의 부모에서 찾으며, worktree의 사본은 쓰지 않고 못 찾으면 거부) | Claude의 main 체크아웃 편집(`docs/tasks/*.md` 제외), `.harness/` 편집, 잠금 파일이 implement를 가리키지 않는 worktree 편집 |
| Bash 가드 | 같은 훅 | Claude의 `gh pr merge`, PR 승인 리뷰, `.harness/locks` 수정, `harness-maintenance`를 담은 `gh pr edit`/`gh pr create`/`gh label`/`gh api` |
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

한계: Bash 가드는 명령 문자열만 검사하므로 우회할 수 있고, Bash로 쓰는 일반 파일은 막지 못한다. Codex 대화형 세션도 훅으로 막지 않는다.
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
