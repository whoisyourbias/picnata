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
| 상태 저장           | SQLite                            |
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
