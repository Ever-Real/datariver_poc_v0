# PREP TEST PUBLICATION READINESS

## 판정

- 범위: PREP에서 사용자가 직접 검증하기 위한 source publication 준비
- publication candidate HEAD: `8f6fcff39c522ce80c575f1868f398a379148ec4`
- coherent product SHA: `138044ab8f819e3bc86d09a9d4d25d3d421b0141`
- remote `dev`: `af97af3c5c77449398711fbf33638aad1f980499`
- readiness: `PASS_FOR_PREP_TEST_PUBLICATION`
- release/production readiness: `NOT_CLAIMED`
- G1/G2: `NOT_APPROVED`
- G3/G4: `NOT_APPROVED`

`138044a..8f6fcff`에는 `.orchestration/**`와 `CURRENT.md` 6경로만 있으며 제품 코드 변경은 없다. candidate worktree는 clean이고 remote `dev`에서 fast-forward 가능한 계보다.

## 제품·증적 관계와 Python T03

- PREP test source HEAD는 제품 SHA 이후의 current/evidence 문서를 포함하는 `8f6fcff`다.
- Python/Alembic T03 경로는 Git source에는 포함되지만 `NOT_RUNTIME_INTEGRATED`다.
- POC Dockerfile은 `frontend/**` 산출물과 Node runtime 모듈만 복사하므로 Python T03는 PREP POC image/runtime에 포함되지 않는다.
- 이 source 포함은 PREP test publication을 막지 않지만, Python T03의 장기 유지/제거는 최종 release 전에 별도 판정해야 한다. runtime 사용으로 재분류하지 않는다.

## Secret / Credential 점검

- tracked secret/key 파일: 없음. tracked 환경 파일은 example 4개뿐이다.
- private-key/AWS/GitHub/Slack/JWT 형태의 tracked token 패턴: 미검출.
- candidate evidence에는 DEV local terminal credential incident의 상태만 기록되고 값은 기록되지 않는다.
- incident: local terminal exposure `YES`, external publication `NO`, rotation `NOT_EXECUTED`.

## PREP_DEPLOYMENT_DELTA

- Dockerfile 변경: `YES`, candidate에 이미 반영. `poc-change-history-scheduler.mjs`, `poc-mcl-capture.mjs` runtime COPY 2개가 추가되었다. 추가 Dockerfile 변경은 connected/internal-registry build에는 필요 없다.
- npm dependency: `@kafkajs/confluent-schema-registry@4.1.0`, `kafkajs@2.2.4` 추가. lockfile 고정.
- `npm ci --ignore-scripts`: candidate Dockerfile 실제 `linux/amd64` build에서 PASS; 370 packages, audit 0.
- Compose 변경: `YES`, candidate에 이미 반영. change-history authority/scheduler/MCL 환경계약 22개가 web service에 추가되었다.
- PostgreSQL: 기존 volume은 `docker-entrypoint-initdb.d` 재실행에 의존하지 않는다. Node `poc-state-store` startup이 동일한 additive `CREATE IF NOT EXISTS`/index/function/trigger 계약을 적용한다. 통제된 선행 적용은 `001-poc-state.sql`을 `psql -v ON_ERROR_STOP=1`로 실행한다.
- rollback: 기본은 candidate web만 중지하고 기존 39080 web을 유지하는 application rollback이다. additive append-only history tables는 삭제하지 않는다. DB 전체 restore는 test history를 잃는 파괴적 별도 결정이다.

## Linux/AMD64 Build

- command: `docker buildx build --platform linux/amd64 --file deploy/poc/Dockerfile.example --build-arg POC_SOURCE_COMMIT=8f6fcff39c522ce80c575f1868f398a379148ec4 --tag datariver-poc:prep-test-8f6fcff-amd64 --load .`
- result: `PASS`
- image ID: `sha256:0886258646acfaafc935e93264bd41db2a1238e35b3d4947e79c8bd67fda7e52`
- image platform: `linux/amd64`
- OCI revision: `8f6fcff39c522ce80c575f1868f398a379148ec4`
- Compose rendered contract: `PASS` with non-secret placeholders.
- repository `verify_static.py`: `NOT_EXECUTED_ENVIRONMENT` because the clean evidence worktree lacks PyYAML; dependency installation was not performed. Prior candidate validation evidence remains unchanged and was not weakened.
- container/PREP/OPS runtime: `NOT_EXECUTED`

## 폐쇄망 전제

- application source는 `origin/dev`로 전달하고 application image를 DEV에서 PREP으로 전달하지 않는다.
- PREP build 전에 `linux/amd64`의 `node:22.19.0-bookworm-slim`, `pgvector/pgvector:0.8.2-pg17-bookworm`, `redis:8.2.6-bookworm`, `neo4j:2026.06.0`을 준비한다.
- exact `frontend/package-lock.json`에 맞는 npm cache 또는 사내 npm mirror가 필요하다. 현재 Dockerfile은 `npm ci --ignore-scripts`를 실행하므로 외부 npm registry도 내부 mirror도 사용할 수 없는 완전 폐쇄 상태에서는 fresh build를 보장하지 않는다.
- DataHub/Kafka/Schema Registry는 candidate가 새로 생성하지 않는 외부 runtime이며 PREP에서 실제 연결계약을 다시 확인한다.

## Model Policy Correction

- `20/30/40/50/60`: Gemini 3.1 Pro High via Antigravity
- `98`: Gemini 3.1 Pro Low via Antigravity
- `00/10/90`: GPT-5.6 Sol 정책 유지
- Gemini/Antigravity unavailable을 선험적으로 가정하지 않는다. 실제 invocation 실패 receipt가 있을 때만 clean checkpoint 후 controlled fallback을 사용한다.

## NOT_EXECUTED

- local `dev` fast-forward
- push / remote publication
- PREP mutation / runtime
- OPS mutation / runtime
- T08 / T09
- credential rotation
