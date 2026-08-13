# DEV-INTEGRATION-CHECKPOINT-01-PLATFORM-REPAIR 증적

## 범위와 provenance

- Task: `DEV-INTEGRATION-CHECKPOINT-01-PLATFORM-REPAIR`
- 역할: `20_PLATFORM_RELEASE Builder`
- exact base SHA: `0f1d491120af2abb5149aa0b9be9b2fe124d1818`
- product commit: `4857b70b1411a6ec78ad9397ee690c41fa59dc7d`
- 검증 시각: `2026-08-14T03:40:36+09:00`
- 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`, uv `0.11.12`, Docker Compose `5.3.1`
- runtime permission mechanism: `NOT_SUPPORTED`; 저장소의 사전 승인된 `LOW_RISK` 범위만 사용
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

제품 커밋은 `deploy/poc/Dockerfile.example`, `deploy/poc/docker-compose.poc.yaml`,
`deploy/poc/.env.example`만 변경한다. 새 service/container/network/dependency/framework는 추가하지
않았고 package/lock 파일도 변경하지 않았다.

## 수정 내용

- POC 서버의 로컬 runtime import closure에 필요한 `poc-change-history-scheduler.mjs`와
  `poc-mcl-capture.mjs`를 runtime image에 복사한다. 기존 `poc-state-store.mjs` 복사는 유지한다.
- `.env.example`에 이미 정의된 `POC_CHANGE_HISTORY_SCHEDULER_*`와 `POC_MCL_*` 21개 설정을
  Compose `web.environment`에 같은 이름과 같은 기본값으로 전달한다.
- private change-history API가 사용하는 server-owned
  `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID`를 `.env.example`과 Compose에 추가한다. 기본값은 비어 있으며
  browser가 제공하거나 덮어쓸 수 없음을 문서화했다.
- scheduler 기본값은 계속 비활성화다. credential과 active subject의 빈 기본값을 유지해 배포 설정을
  임의로 만들지 않는다.

## 검증 결과

| 명령/검증 | 결과 | 근거 |
|---|---|---|
| read-only local import/COPY closure 검사 | `PASS` | `poc-server.mjs`에서 도달 가능한 로컬 `.mjs` 4개가 모두 exact Docker `COPY`에 존재 |
| read-only `.env.example`/Compose 계약 검사 | `PASS` | active subject, scheduler, MCL 총 22개 key와 기본값이 정확히 일치; active subject는 blank, scheduler는 disabled |
| `docker compose --env-file deploy/poc/.env.example -f deploy/poc/docker-compose.poc.yaml config --quiet` | `PASS` | exit 0, 렌더링 값 출력 없음 |
| `npm run build:poc` (`frontend`) | `FAIL_ENVIRONMENT`, exit 127 | `node_modules` 부재로 shell이 `tsc: command not found`를 반환; npm dependency 설치는 수행하지 않음 |
| `uv run python scripts/verify_static.py` | `PASS` | 기존 정적 검증이 Compose, build/release context, source integrity 등 전체 항목 통과 |
| `git diff --check` | `PASS` | whitespace 오류 없음 |
| 제품 변경 경로 allowlist | `PASS` | 허용된 제품 파일 3개만 변경 및 커밋 |

`uv run`은 기존 프로젝트 선언으로 ignored `.venv` 검증 환경을 만들었지만 추적 파일이나 dependency
선언/lock을 변경하지 않았다. `npm run build:poc`의 환경 실패는 정적 검증 `PASS`로 대체했으며 Node 22 및
target image build 성공을 주장하지 않는다.

## NOT_EXECUTED와 잔여 gate

- Docker image build 및 container/service/network start/stop/recreate: `NOT_EXECUTED`
- scheduler 실행과 Kafka/Schema Registry/PostgreSQL/DataHub runtime 연동: `NOT_EXECUTED`
- 실제 credential 또는 active subject 설정: `NOT_EXECUTED`
- Node 22, Linux/amd64, PREP, OPS, TARGET 검증: `NOT_EXECUTED`
- push, merge, publication, G1-G4 승인: `NOT_EXECUTED`

결론은 `REPAIRED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`이다. 이 증적은 local source/static
검증만 나타내며 target 또는 운영 준비 완료를 주장하지 않는다.
