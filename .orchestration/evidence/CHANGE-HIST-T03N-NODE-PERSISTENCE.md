# CHANGE-HIST-T03N Node POC persistence evidence

- 상태: `IMPLEMENTED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`
- 검증일: 2026-08-14 (KST)
- exact base: `91551852d23ce0e1800162af406c1b053d0106eb`
- product commit: `865175d532c4ff0e3f3e1b2bcddb5045b045972e`
- 브랜치/worktree: `Ever-Real/change-hist-t03n-node-persistence` / `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t03n-node-persistence`
- architecture deviation: 없음
- 새 dependency: 없음

## 범위와 런타임 판정

실제 POC persistence 진입점은 Node `createPocStateStore()`이며, Compose PostgreSQL fresh init과
Node startup의 `CREATE ... IF NOT EXISTS`가 같은 관계를 준비한다. 이 Task는 기존 PostgreSQL
service와 연결 설정을 재사용했으며 service/container/runtime를 시작·중지·재구성하지 않았다.

Python/Alembic T03 (`backend/alembic/versions/0096_change_history_persistence.py`,
`backend/src/datariver/infrastructure/db/change_history.py`) 상태는 **`NOT_RUNTIME_INTEGRATED`** 이다.
해당 구현은 삭제·되돌림·수정하지 않았고 Node POC에서 import하거나 실행하지 않았다.

## 구현 계약

- `poc_change_history_sources`: credential/endpoint를 저장하지 않는 SHA-256 source identity와
  provider/schema contract identity.
- `poc_change_history_ledger_events`: 결정적 source-event/semantic event identity, source
  partition/offset/ordinal unique fence, bounded normalized before/after JSON과 계산된 SHA-256,
  UTC `timestamptz`, append-only UPDATE/DELETE trigger.
- `poc_change_history_checkpoints`: source/topic/partition PK, first exact/next offset, 마지막 연속
  event/time, monotonic application-level fence. Ledger insert와 checkpoint advance는 동일 DB
  transaction에서만 수행한다.
- `poc_change_history_cr_link_events`: PRIMARY/CANDIDATE와 SET/CLEAR/ADD/REMOVE 닫힌 vocabulary,
  per-ledger version/prior-hash chain, idempotency-key/request hash, append-only trigger. 기존 CR
  aggregate/state/transition/revision/approval/target binding은 읽거나 쓰지 않는다.
- canonical JSON lexical ordering과 Node SHA-256으로 replay 순서에 독립적인 identity를 만든다.
  동일 message replay는 저장 hash를 대조하고 checkpoint를 재전진시키지 않는다. 동일 field의
  복수 semantic event는 ordinal로 허용한다. stale/gap offset과 stale link chain은 fail closed 한다.
- `raw`, `payload`, `aspect`, `schemaMetadata`, `previousAspectValue` 중첩 key를 Node validation과
  PostgreSQL CHECK에서 거부한다. 원본 MCL/aspect 문서를 복제하지 않는다.
- 메모리 fallback은 change-history persistence에 허용하지 않는다. PostgreSQL 미설정 시 명시적
  오류를 반환하며 기존 `poc_state`, Redis cache, pgvector embedding 동작은 유지한다.

## 최종 검증

의존성 설치 없이 `/Volumes/SSD_Mac/workspace/datariver_poc_v0/frontend/node_modules`의 기존
snapshot을 임시 `/tmp/datariver-t03n-full.fuOKgI` 검증 복제에서 재사용했다.

| 명령 | 결과 |
|---|---|
| `npm run lint` | PASS, 전체 frontend ESLint |
| `npm run build:poc` | PASS, Vite build; 기존 500 kB chunk warning만 존재 |
| `node --test poc-state-store.test.mjs` | PASS 5/5: fresh/existing DDL parity, insert/replay/fanout, checkpoint rollback/no-advance, CR link append/idempotency/stale chain, raw/UTC negatives |
| `npm run test:poc-server` | PASS 28/28: 기존 `poc_state`, Redis fallback, Catalog embedding generation 및 provider/server 회귀 |
| `git diff --check` | PASS |
| product commit 후 `git status --short` | CLEAN |

### 검증 준비 중 발생한 비제품 실패

- worktree 자체에 `node_modules`가 없어 최초 직접 Node test가 `ERR_MODULE_NOT_FOUND: pg`로
  중단됐다. dependency 설치는 수행하지 않았다.
- 첫 임시 symlink 방식은 ESM realpath가 원 worktree를 가리켜 같은 import 오류가 발생했다.
- 첫 full-copy 명령은 잘못된 working directory 때문에 복제가 되지 않았고 dependency 없는 source
  test를 중단했다. 저장소/runtime/service에는 effect가 없었다.
- 올바른 full-copy에서 첫 focused run은 `deploy/` fixture가 누락되어 DDL parity 1건만 ENOENT,
  나머지 4건은 PASS였다. `deploy` read-only symlink를 보완한 최종 run은 5/5 PASS였다.

## NOT_EXECUTED

- live PostgreSQL DDL 적용/기존 DB upgrade/runtime startup: DB/runtime mutation 금지로 미실행
- Kafka/DataHub consumer, Schema Registry decode, scheduler/nightly capture: 이 Task 범위 밖이며
  dependency/invocation Task 이후 단계
- Python T03 실행·통합·삭제: `NOT_RUNTIME_INTEGRATED`, 미실행/미변경
- dependency/package-lock install 또는 변경
- service/container/provider/Redis/Neo4j/Kafka/DB mutation
- CR domain state/API/UI/IAM/role-system authority 변경
- merge, push, PREP, OPS, G1/G2/G3/G4

## 잔여 단계

T03N persistence foundation 자체 blocker는 없다. 다음 최소 단계는 별도 승인된 Node Kafka/Schema
Registry dependency와 server-owned capture invocation을 이 API에 연결하는 것이다. CR link API와
role/system authorization은 server-authoritative actor 경계가 준비된 뒤 별도 T06에서 수행해야 하며,
이 Task 결과만으로 runtime capture 또는 CR access acceptance를 주장하지 않는다.
