# Change Management 최종 문서 계약 보정 증적

- Task: `CHANGE_MANAGEMENT_CLOSEOUT_FINAL_DOC_FIX_AND_G1_G2_READINESS`
- 검증 시각: `2026-08-15T16:23:37Z`
- Functional Product SHA: `4aea6d19c64253130e00d997c2837b74fac4837d`
- Runtime Validation Evidence SHA: `313a559bdd9300d3ee2021935d2dbac0319bafd1`
- Productization Documentation SHA: `a90ef2d1bce368310b0088280dacff2f785ef703`
- 이전 Closeout Evidence SHA: `80b2e4998880f33e9d7b2fc63165eaebcfddf1cb`
- 시작 시 `origin/dev`: `737cee10daaf3af1680e11cdb43b2779d0865756`
- 결과: `PASS_STATIC_DOCUMENTATION_CLOSEOUT`

## 적용한 최종 계약

- Kafka connectivity probe는 `loadPocMclCaptureConfig()`의 brokers/client ID/SSL/SASL을
  재사용하고 credential을 출력하지 않는다.
- Schema Registry discovery는 같은 parsed Registry host/optional username/password로 anonymous/authenticated
  Registry를 모두 다루며 subject/version/ID/type/SHA-256만 남긴다.
- source identity는 provider name/version, Kafka cluster ID/topic, Registry subject/schema hash 여섯
  descriptor의 candidate hash를 DB exact key로 조회할 때만 재사용한다.
- checked-out HEAD를 shell `POC_SOURCE_COMMIT`으로 Compose build에 전달하고 image OCI revision을
  read-back하여 source/build/image equality를 검증한다.
- Compose command는 same-host external-network overlay(A)와 remote DNS/TCP base-only(B)를 분리했다.
- scheduler lock은 logical deployment 간 unique, 같은 deployment의 restart/rebuild/release 간 stable이다.
- ADR-0124는 `SourceBoundary`/opaque position과 semantic storage guarantee를 정의하고 Kafka/PostgreSQL
  구현 세부사항을 domain port에서 제거했다.
- 현재 secret 계약은 ignored `.env`/deployment environment이며 secret files/injection은 target
  backlog으로 분리했다.
- tracked `Dockerfile.example`이 canonical target이며 `Dockerfile.local`은 임시 DEV/PREP compatibility이다.
- 기존 volume은 `001-poc-state.sql` 수동/idempotent 재적용이며 versioned migration framework는
  미구현이다.

## 정적 검증

| 항목 | 결과 |
|---|---|
| document links/paths/fences | PASS |
| Runbook/Productization Bash fenced commands | `bash -n` PASS |
| Runbook Node heredoc 3개 | `node --check --input-type=module` PASS |
| base Compose | PASS |
| base + DataHub external-network overlay | PASS |
| Airflow Compose | PASS with non-secret validation placeholders |
| `.env.example` ↔ Compose | 79/79, missing 0 |
| MCL/Change History source env ↔ example | missing 0 |
| actual secret/IP/64-hex value scan | actual finding 0; generic loopback만 존재 |
| ADR current/target wording | PASS |
| canonical backlog markers | PASS |
| `git diff --check` | PASS |
| Functional Product SHA 이후 runtime/package/lock/SQL/Compose/Dockerfile 변경 | 0 |

문서/sample config만 변경했으므로 MCL/CR runtime mutation E2E는 반복하지 않았다. product,
container, DB, Kafka, DataHub, PREP, OPS를 수정하지 않았고 push도 수행하지 않았다.

## Backlog과 gate

canonical master backlog에 `REPRODUCIBLE_DEPLOYMENT_ACCEPTANCE`, `POC_SCHEMA_MIGRATION_CONTRACT`,
Dockerfile.local retirement, secret injection, legacy export helper, browserless loopback fallback, Timeline,
modular architecture, Vector/Chat/PREP/OPS/midnight/GX/Vite 항목을 확인·보완했다.

- G1/G2: `READY_FOR_APPROVAL`
- G3/G4: `NOT_REQUESTED`
- publication/push: `NOT_EXECUTED`
