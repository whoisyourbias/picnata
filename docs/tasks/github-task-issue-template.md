# GitHub Task 이슈 템플릿

## 목표
GitHub에서 작업 이슈를 만들 때 작성자가 목표와 가정을 기록할 수 있는 Task 템플릿을 제공한다.

## 범위
- 포함: 요청에서 제공한 Markdown 이슈 템플릿 한 개를 추가한다.
- 제외: 이슈 양식 설정, 자동화 워크플로, 기존 이슈 변경.

## 변경 대상
- `.github/ISSUE_TEMPLATE/task.md`

## 동작 명세
기본 브랜치에 반영되면 GitHub 이슈 템플릿 선택 화면에서 `Task`와 설명 `작업 목표 및 가정 정의`를 표시한다. 선택 시 제목, 라벨, 담당자의 기본값은 비어 있으며 이슈 본문은 아래 내용을 사용한다.

```markdown
---
name: Task
about: 작업 목표 및 가정 정의
title: ''
labels: ''
assignees: ''
---

## 🎯 목표 (Goal)

<!-- 해당 이슈를 통해 달성하고자 하는 목표 -->

-

## 📌 가정 (Assumptions)

<!-- 작업의 전제 조건, 제약사항 및 기술적 가정 -->

-
```

## 완료 조건
- [ ] 지정된 경로에 UTF-8 Markdown 파일이 있고, 프런트 매터의 다섯 필드와 본문의 제목, 주석, 빈 목록 항목이 명세와 일치한다.
- [ ] 구현 변경에는 템플릿 파일 한 개만 포함된다. 정적 파일 검증을 수행하며 별도의 테스트 파일은 필요하지 않다.

## 검증 명령
```text
python -c "from pathlib import Path; p=Path('.github/ISSUE_TEMPLATE/task.md'); s=Path('docs/tasks/github-task-issue-template.md').read_text(encoding='utf-8'); expected=s.split(chr(96)*3+'markdown\n',1)[1].split('\n'+chr(96)*3,1)[0]; assert p.read_text(encoding='utf-8').strip().splitlines() and [x.rstrip() for x in p.read_text(encoding='utf-8').strip().splitlines()] == expected.splitlines()"
```

## 가정
- GitHub 기본 브랜치는 `main`이다. 구현은 승인 후 하네스가 만드는 전용 worktree에서 진행한다.
- 빈 목록 항목 뒤의 공백은 생략할 수 있다.

## 열린 질문
없음
