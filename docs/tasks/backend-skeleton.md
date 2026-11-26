# Spring Boot 백엔드 골격과 검증 명령

## 목표
`backend/`에 빌드·테스트가 되는 Spring Boot 애플리케이션 골격을 만들어, 이후 모든 하네스 작업이 같은 검증 명령(`test`)으로 verify할 수 있게 한다.

## 범위
- 포함
  - `backend/` 아래 Gradle 단일 프로젝트 (Groovy DSL), Gradle Wrapper 포함
  - Spring Boot 애플리케이션 진입점 1개
  - 의존성: `spring-boot-starter-web`, `spring-boot-starter-actuator`, `spring-boot-starter-test`
  - Actuator health 엔드포인트 노출 (`/actuator/health`)
  - 테스트 2개: 컨텍스트 로드, health 응답
  - 루트 `.gitignore`에 `backend/build/`, `backend/.gradle/` 추가
- 제외
  - DB(PostgreSQL, pgvector), JPA, Flyway 설정
  - Spring Security, OAuth
  - 기획안 8.5의 도메인 모듈(Image Analysis, Recommendation 등) 패키지와 코드
  - AWS·Bedrock·CLAP 연동, Docker, CI의 백엔드 빌드 단계
  - 프론트엔드, Python 배치

## 변경 대상
- `backend/settings.gradle`, `backend/build.gradle`
- `backend/gradlew`, `backend/gradlew.bat`, `backend/gradle/wrapper/gradle-wrapper.properties`, `backend/gradle/wrapper/gradle-wrapper.jar`
- `backend/src/main/java/com/picnata/PicnataApplication.java`
- `backend/src/main/resources/application.yml`
- `backend/src/test/java/com/picnata/PicnataApplicationTests.java`
- `backend/src/test/java/com/picnata/HealthEndpointTests.java`
- `.gitignore`

## 동작 명세
- 빌드 설정
  - Java toolchain 21. Spring Boot는 구현 시점의 최신 GA 버전을 쓰고 `build.gradle`에 정확한 버전을 고정한다.
  - `group = 'com.picnata'`, 루트 프로젝트 이름 `picnata-backend`.
- 애플리케이션
  - `com.picnata.PicnataApplication`이 `@SpringBootApplication` 진입점이다.
  - `application.yml`: `spring.application.name: picnata-backend`, `management.endpoints.web.exposure.include: health`.
  - DB 의존성이 없으므로 외부 서비스 없이 기동한다.
- 엔드포인트
  - `GET /actuator/health` → HTTP 200, 본문 `{"status":"UP"}` (JSON의 `status` 값이 `UP`).
  - 그 밖의 Actuator 엔드포인트는 노출하지 않는다. 예: `GET /actuator/env` → 404.
- 공개 인터페이스 변경: 없음 (신규).

## 완료 조건
- [ ] `PicnataApplicationTests`: `@SpringBootTest` 컨텍스트 로드가 성공한다.
- [ ] `HealthEndpointTests`: `@SpringBootTest(webEnvironment = RANDOM_PORT)`에서 `GET /actuator/health`가 200이고 `status`가 `UP`이다.
- [ ] `HealthEndpointTests`: `GET /actuator/env`가 404다.
- [ ] 검증 명령이 네트워크 외 다른 외부 서비스(DB 등) 없이 종료 코드 0으로 끝난다.
- [ ] 하네스 자체 테스트(`python -m unittest discover -s tests`)가 계속 통과한다.

## 검증 명령
```
backend/gradlew.bat -p backend test
```
하네스가 이 명령을 작업 worktree에서 실행한다 (`run`은 이 절의 첫 코드 블록을 검증 명령으로 읽고, 경로가 있는 실행 파일은 worktree 기준으로 찾는다).

## 가정
- 빌드 도구는 Gradle(Groovy DSL)이다. 기획안에 명시가 없어 Spring Boot 기본값을 따랐다.
- 백엔드는 저장소 루트가 아닌 `backend/`에 둔다. 루트에는 하네스가 있고 이후 프론트엔드·Python 배치가 추가될 예정이기 때문이다.
- 패키지 루트는 저장소 이름을 따라 `com.picnata`로 한다. 기획안의 프로젝트명은 "미정"이다.
- 이 PC의 JDK는 21(`openjdk 21.0.11`)이라 toolchain을 21로 확정한다.
- Gradle 9.9.2가 이 PC의 PATH에 설치돼 있다. Wrapper는 구현자(Claude)가 implement 단계에서 `gradle -p backend wrapper`로 만든다. 그러면 `gradle-wrapper.jar`는 에이전트가 쓰는 바이너리가 아니라 Gradle이 생성한 파일이다. Wrapper의 Gradle 버전은 설치된 9.9.2로 고정한다 (`--gradle-version 9.9.2`).
- 구현자는 Claude(`claude`)다. implement 단계에서 허용된 `gradle`/`gradlew` 명령으로 빌드·테스트를 직접 돌려 볼 수 있다 (`python -m unittest` 외 허용 명령은 `harness-build-tools` 작업에서 추가됐다). 실행이 거부되면 최종 응답에 이유를 적고, 실패는 verify에서 드러난다.
- Spring Boot 버전은 구현자가 구현 시점에 Gradle 9.9.2와 JDK 21에서 빌드되는 최신 GA 버전을 조회해 고르고, 조회한 곳과 고른 버전을 최종 응답에 쓴다. 조회가 불가능하면 구현자가 아는 가장 최근 GA를 쓰고 그 사실을 적는다.
- implement 단계의 네트워크 접근(의존성·플러그인 다운로드)은 Claude 구현자에게 열려 있다고 가정한다. 막혀 있으면 구현자는 그 사실을 보고하고, 이 작업은 사람이 개입해 이어간다 (`run --adopt`).

## 열린 질문
없음
