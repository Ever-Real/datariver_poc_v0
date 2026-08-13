# CHANGE-HIST-T03N 독립 검증 증거

- 판정: **PASS**
- 검증일: 2026-08-14 (KST)
- exact candidate: `b29c126c85c0b2edd6e07a3ba7e31d0e79a50cc4`
- exact base: `91551852d23ce0e1800162af406c1b053d0106eb`
- product commit: `865175d532c4ff0e3f3e1b2bcddb5045b045972e`
- 검증 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`
- Node 22 판정: `TARGET_RECHECK_REQUIRED` — 로컬 Node 22 실행 파일이 없어 실행하지 못했다.
- 제품 repair: `NOT_EXECUTED`

## 독립 검증 방식

검증 브랜치의 clean HEAD가 exact candidate와 일치함을 확인한 뒤, candidate를
`/tmp/datariver-t03n-validation.0TtsZT/repo`에 detached 임시 복제했다. dependency 설치 없이
`/Volumes/SSD_Mac/workspace/datariver_poc_v0/frontend/node_modules`를 임시 복제의
`frontend/node_modules`에 연결해 재사용했고, 두 `package-lock.json`이 동일함을 확인했다.

base부터 candidate까지 변경은 아래 5개 경로뿐이다.

- `.orchestration/evidence/CHANGE-HIST-T03N-NODE-PERSISTENCE.md`
- `.orchestration/receipts/CHANGE-HIST-T03N-NODE-PERSISTENCE.md`
- `deploy/poc/postgres-init/001-poc-state.sql`
- `frontend/poc-state-store.mjs`
- `frontend/poc-state-store.test.mjs`

product commit 이후 candidate까지의 두 번째 commit은 기존 evidence/receipt 2개만 변경한다.
dependency/lockfile, Python/Alembic T03, 서버/API/UI, container/service 경로 변경은 없다.

## 실행 결과

| 검증 | 결과 |
|---|---|
| `node --test poc-state-store.test.mjs` | PASS 5/5 |
| `npm run lint` | PASS, 전체 frontend ESLint |
| `npm run build:poc` | PASS, TypeScript + Vite POC build; 기존 500 kB chunk warning만 존재 |
| build 후 `npm run test:poc-server` | PASS 28/28 |
| Node/runtime DDL과 fresh-init DDL 정규화 비교 | PASS, 9개 statement exact parity |
| `git diff --check 9155185..b29c126` | PASS |
| 변경 경로 allowlist | PASS |
| 추가 product line의 credential/secret/host/port/timezone/TTL scan | PASS, 발견 없음 |
| Python T03 경로 static diff | PASS, 변경 없음 |

임시 복제에서 build 전에 먼저 실행한 POC server suite는 `dist-poc`가 아직 없어 root 응답 1건이
`404 != 200`으로 실패했고 나머지 27건은 통과했다. 요구된 POC build를 수행한 뒤 같은 exact
candidate에서 재실행한 최종 server regression은 28/28 PASS였다.

## 계약 판정

- transaction/checkpoint: capture는 `BEGIN` 후 source와 checkpoint를 준비하고 checkpoint row를
  `FOR UPDATE`로 잠근다. ledger insert/replay hash 검증 뒤 `next_offset` CAS와 ledger write를 같은
  transaction에서 commit하며, 오류 경로는 `ROLLBACK`한다. focused test가 ledger 실패와 offset
  gap에서 checkpoint no-advance를 검증했다.
- dedup/replay: source/topic/partition/offset에서 source-event identity를 만들고 canonical sort 후
  ordinal을 부여한다. source-event/ordinal 및 source-position/ordinal unique fence가 있으며,
  conflict 시 저장 `event_hash` 불일치는 fail closed 한다. 순서가 바뀐 동일 message replay와 동일
  field의 복수 semantic event가 focused test에서 통과했다.
- CR link: idempotency-key hash와 request hash를 대조하고, per-ledger version/prior-hash chain의
  stale 요청을 거부한다. candidate/primary append와 exact replay/conflict가 focused test에서 통과했다.
- append-only: runtime DDL과 fresh-init DDL 모두 ledger/link table에 `BEFORE UPDATE OR DELETE`
  trigger를 각각 2개 정의한다. checkpoint만 fenced update 대상이며 ledger/link delete, TTL,
  truncate 경로는 추가되지 않았다.
- bounded/static: before/after는 16,384-byte object로 제한되고 nested `raw`, `payload`, `aspect`,
  `schemaMetadata`, `previousAspectValue`를 Node와 PostgreSQL 양쪽에서 거부한다. SHA-256 형식,
  closed category/aspect/operation vocabulary, UTC `Z` 입력 및 `timestamptz` 저장을 확인했다.
- regression: 기존 `poc_state`, Redis fallback, Catalog embedding generation, provider/server 경로의
  28개 회귀가 build 후 모두 통과했다.
- Python T03: `backend`는 candidate diff에 없고 Node POC의 새 append API를 호출하는 runtime 경로도
  아직 없다. 따라서 Python/Alembic T03은 보존되며 `NOT_RUNTIME_INTEGRATED`이고, T03N은 후속 Node
  capture/invocation이 사용할 persistence foundation만 제공한다.

## Findings 및 미실행 항목

blocking/non-blocking code finding은 없다. 다만 아래 target/environment 검증은 이 PASS에 포함되지
않는다.

- Node 22.19+ target 재실행: `TARGET_RECHECK_REQUIRED`
- live PostgreSQL fresh init/기존 DB DDL 적용, trigger 실행, 실제 rollback/concurrency:
  active DB mutation 금지에 따라 `NOT_EXECUTED`
- Kafka/DataHub/Schema Registry consumer와 scheduler/nightly capture: `NOT_EXECUTED`
- dependency 설치/변경, runtime/container/provider/DB mutation: `NOT_EXECUTED`
- merge, push, PREP, OPS 및 G1/G2/G3/G4: `NOT_EXECUTED` / `NOT_APPROVED`

이 판정은 exact candidate의 로컬 정적·테스트 검증 PASS이며, Node 22 및 실제 PostgreSQL target
acceptance나 runtime capture 활성화를 승인하지 않는다.
