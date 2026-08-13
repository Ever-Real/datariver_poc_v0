# DEV-INTEGRATION-CHECKPOINT-01-PLATFORM-VALIDATION 독립 검증 증적

## 범위와 provenance

- Task: `DEV-INTEGRATION-CHECKPOINT-01-PLATFORM-VALIDATION`
- 역할: `50_QUALITY_VALIDATION`
- exact base SHA: `0f1d491120af2abb5149aa0b9be9b2fe124d1818`
- product commit: `4857b70b1411a6ec78ad9397ee690c41fa59dc7d`
- candidate SHA: `cd1eaf3fbb22bd7caba7f228dd12856e048e2fe2`
- 검증 시각: `2026-08-14T03:46:39+09:00`
- 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`, uv `0.11.12`, Docker Compose `5.3.1`
- runtime permission mechanism: `NOT_SUPPORTED`; 저장소의 사전 승인된 `LOW_RISK` 범위만 사용
- 제품 수정: 없음

검토한 제품 파일은 정확히 다음 3개다.

1. `deploy/poc/Dockerfile.example`
2. `deploy/poc/docker-compose.poc.yaml`
3. `deploy/poc/.env.example`

## 독립 검증 결과

| 명령/검증 | 결과 | 근거 |
|---|---|---|
| fresh `npm ci` (`frontend`) | `PASS` | exit 0, 368 packages 설치, 취약점 0 |
| `npm run build:poc` (`frontend`) | `PASS` | `tsc -b`와 Vite POC build exit 0 |
| read-only local import/Docker `COPY` closure 검사 | `PASS` | `poc-server.mjs`에서 도달 가능한 local runtime `.mjs` 4개와 exact `COPY` 4개가 일치 |
| read-only runtime env/`.env.example`/Compose 계약 검사 | `PASS` | active subject, scheduler, MCL 총 22개 key와 기본값이 정확히 일치 |
| disabled/blank default 검사 | `PASS` | scheduler `false`, active subject와 credential 기본값은 blank |
| `docker compose --env-file deploy/poc/.env.example -f deploy/poc/docker-compose.poc.yaml config --quiet` | `PASS` | exit 0, stdout/stderr 값 출력 없음 |
| `uv run python scripts/verify_static.py` | `PASS` | Compose, build/release context, source integrity를 포함한 전체 정적 검증 통과 |
| product path/topology/dependency/민감 기본값 검사 | `PASS` | 제품 변경은 allowlist 3개뿐이고 service 4개/network 1개 유지, dependency 파일 변경 0, 추가 민감 기본값은 blank |
| `git diff --check 0f1d491..4857b70` | `PASS` | whitespace 오류 없음 |

`npm ci`, POC build 및 `uv run`은 추적 파일을 변경하지 않았다. Vite의 500 kB 초과 chunk 경고는
기존 build warning이며 이 플랫폼 패키징 계약의 실패는 아니다.

## Finding과 경계

- blocking/non-blocking finding: 없음
- Docker runtime image는 server import closure에 필요한
  `poc-server.mjs`, `poc-state-store.mjs`, `poc-change-history-scheduler.mjs`,
  `poc-mcl-capture.mjs`를 모두 복사한다.
- Compose는 runtime이 참조하는 optional active-subject/scheduler/MCL 22개 설정을
  `.env.example`과 같은 이름 및 같은 기본값으로 `web.environment`에 전달한다.
- scheduler는 기본 비활성화이며 active subject, SASL/Schema Registry 자격증명은 빈 기본값이다.
- base 대비 새 service, container, network, dependency 또는 framework를 추가하지 않았다.
- 실제 secret/credential을 만들거나 출력하지 않았고 하드코딩하지 않았다.

## 실행하지 않은 항목

- Docker image build 및 container/service/network lifecycle
- scheduler와 Kafka/Schema Registry/PostgreSQL/DataHub 실제 runtime 연동
- 실제 credential 또는 active subject 설정
- Node 22, Linux/amd64, PREP, OPS, TARGET 검증
- push, merge, publication, PREP/OPS 수행 및 G1-G4 승인

결론은 `INDEPENDENT_VALIDATION_PASS`다. 이 증적은 지정된 local source/static/platform 계약만
검증하며 target 또는 운영 준비 완료를 주장하지 않는다.
