# 프로젝트 작업 지침

- 프로젝트 요구사항과 아키텍처는 [서비스 기획안](docs/service-plan-v0.1.md)을 참고한다.
- 배정된 작업 명세의 범위와 완료 조건을 따른다.
- 각 작업은 배정된 worktree에서 진행한다. 다른 작업의 worktree를 수정하지 않는다.
- 변경을 검증하고 실행한 명령과 결과를 인수인계한다.
- 구현과 교차 리뷰 절차는 [협업 운영안](docs/agent-collaboration.md)을 따른다.
- 하네스(`python -m harness.orchestrator run ...`)가 배정한 작업은 그 worktree에서만 수행하고, 직접 `git commit`하지 않는다. 구현 요청은 명세를 작성해 `run`으로 진행할 수 있다.
- 사용자가 기능을 요청하면 바로 구현하지 않는다. 먼저 [명세 프롬프트](harness/prompts/spec.md)의 형식으로 요청을 구체화한 명세(`docs/tasks/<작업 ID>.md`)를 쓰고, 가정과 열린 질문을 사용자에게 보여 승인받은 뒤 구현한다. 하네스에서는 `python -m harness.orchestrator spec <작업 ID> "<요청>" <claude|codex>`가 같은 일을 한다.
