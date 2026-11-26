# 프로젝트 작업 지침

- 프로젝트 요구사항과 아키텍처는 [서비스 기획안](docs/service-plan-v0.1.md)을 참고한다.
- 배정된 작업 명세의 범위와 완료 조건을 따른다.
- 각 작업은 배정된 worktree에서 진행한다. 다른 작업의 worktree를 수정하지 않는다.
- 변경을 검증하고 실행한 명령과 결과를 인수인계한다.
- 구현과 교차 리뷰 절차는 [협업 운영안](docs/agent-collaboration.md)을 따른다.
- 하네스(`python -m harness.orchestrator run <작업 ID> <claude|codex>`)가 배정한 작업은 그 worktree에서만 수행하고, 직접 `git commit`하지 않는다. 하네스가 단계마다 트레일러가 달린 커밋을 `harness/<작업 ID>` 브랜치에 남기고 push한다.
- 사용자가 기능을 요청하면 바로 구현하지 않는다. 먼저 [명세 프롬프트](harness/prompts/spec.md)의 형식으로 요청을 구체화한 명세(`docs/tasks/<작업 ID>.md`)를 쓰고, 가정과 열린 질문을 사용자에게 보여 준다. 열린 질문이 없으면 `python -m harness.orchestrator propose <작업 ID>`로 명세 PR(`spec/<작업 ID>`)을 올린다. 사용자가 그 PR을 main에 머지하면 승인이며, 그 뒤에 `run`으로 구현한다(`--wait SECONDS`로 머지를 기다릴 수 있다). 에이전트는 PR을 머지하거나 대신 승인하지 않는다. 하네스에서는 `python -m harness.orchestrator spec <작업 ID> "<요청>" <claude|codex>`가 명세 작성을 대신한다.
- 검증을 통과하면 하네스가 구현 PR을 연다. 머지는 사람이 한다. 단계는 `python -m harness.orchestrator status <작업 ID>`로 확인한다.
- 이 규칙은 강제된다. Claude Code는 `.claude/settings.json`의 가드 훅이 main 체크아웃 편집(명세 `docs/tasks/*.md` 제외)과 `.harness/` 편집을 거부하고, worktree는 잠금 파일(`.harness/locks/<작업 ID>.json`)이 implement 단계를 가리킬 때만 편집을 허용한다. `gh pr merge`, PR 승인 리뷰, 잠금 파일을 건드리는 Bash 명령도 거부한다. 명세 PR이 머지되지 않았으면 `run`이 거부한다. `main` 직접 커밋은 `.githooks/pre-commit`이, 커밋 트레일러로 명세 승인·리뷰·검증이 확인되지 않는 PR 머지는 CI(`harness-gate`)가 막는다. 거부되면 우회하지 말고 명세부터 작성한다.
