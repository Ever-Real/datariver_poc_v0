# CHANGE-HIST-T05 R1 독립 재검증 증거

## 판정과 범위

- 최종 판정: `FAIL`
- owner role: `50_QUALITY_VALIDATION`
- exact candidate HEAD: `0df91292f0e1a04992fc7227d94084df81092e0b`
- exact product repair SHA: `d84456b5b4581f368854a6710656adbaf54bfa7c`
- compare validation SHA: `15c981beae6006d066744d579f4e3eeee206cf34`
- 검증 worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-r1-validation`
- 시작 상태: exact candidate HEAD, untracked 포함 변경 0건
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

builder 결론을 acceptance로 사용하지 않고 제품 diff, adapter 제어 흐름, 기존 회귀와 임시 독립
harness를 새로 검증했다. 제품 source/test/config는 수정하지 않았고 이 문서와 대응 receipt만
작성했다.

## 후보 provenance와 allowlist

commit 분리는 정확했다.

- `d84456b5b4581f368854a6710656adbaf54bfa7c`의 parent는
  `15c981beae6006d066744d579f4e3eeee206cf34`이며 제품/테스트 4개 경로만 변경한다.
  - `frontend/poc-server.mjs`
  - `frontend/poc-state-store.mjs`
  - `frontend/poc-server.test.mjs`
  - `frontend/poc-catalog-performance.test.mjs`
- `0df91292f0e1a04992fc7227d94084df81092e0b`의 parent는 exact product repair SHA이며 R1
  evidence/receipt 2개만 추가한다.
- `git diff --check 15c981b..0df9129`, conflict-marker scan, 시작 status 및 제품/evidence
  allowlist는 `PASS`였다.
- R1 evidence/receipt의 exact base, product repair SHA, 검증 provenance, 테스트와
  `NOT_EXECUTED` 기록은 Git과 일치했다.

## Finding disposition

### F-01 — `PASS`

임시 독립 provider harness로 아래 각 scroll 응답을 fresh process에서 재현했다.

- `total=2`이나 terminal unique item이 1개인 불완전 page
- 문자열 total과 page 간 inconsistent total
- 두 page에 같은 identity를 반환하는 duplicate-induced cardinality gap
- 숫자 malformed cursor, immediate repeated cursor
- unique cardinality가 total에 이미 도달한 뒤 continuation cursor
- 첫 page 성공 뒤 later-page HTTP 502
- `total=0`, empty items, terminal cursor의 유효한 zero inventory

앞의 모든 failure case는 HTTP warming/failure 상태에서 PostgreSQL projection write가 0회였고
불완전 generation을 commit하지 않았다. exact zero case만 빈 items projection을 1회 commit했다.
기존 performance regression도 terminal partial last-good 유지, later-page failure 유지, valid zero
commit/fresh-process reuse를 통과했다. cursor cycle처럼 page bound까지 진행하는 경우도 final commit
전에 bound failure하므로 incomplete generation을 노출하지 않는다.

### F-02 — `FAIL` — 실제 state-store에서 PostgreSQL read failure 시 Redis fallback 불가

PostgreSQL이 정상 응답하는 split-success는 `PASS`다. stale Redis와 newer PostgreSQL을 함께
주입한 fresh server는 `postgres_new`만 반환했고 PostgreSQL read 1회, Redis read 0회였다.
PostgreSQL 값이 invalid이지만 read 자체는 성공한 경우 Redis로 무결성 실패를 가리지 않고 503/provider
refresh로 fail safe했으며, invalid Redis도 current projection이나 valid zero로 취급하지 않았다.

그러나 `createPocStateStore()`의 실제 adapter 경로에서 PostgreSQL read/initialization 자체가 실패하면
요구된 Redis availability fallback에 도달할 수 없다. `start()`는 한 shared promise 안에서 PostgreSQL
table/query 초기화를 먼저 수행한 뒤 Redis client를 연결한다. PostgreSQL 단계가 throw하면 Redis는
초기화되지 않은 채 `starting`을 reset하고 오류를 다시 던진다. `storedDatahubInventory()`가 그 오류를
catch하고 `cacheGet()`을 호출해도 `cacheGet()`의 `start()`가 같은 PostgreSQL 실패를 다시 수행하므로
Redis get까지 진행하지 못한다.

독립 실제-adapter harness에서 injected database pool의 startup/read query를 실패시키고 관찰 가능한
local fake Redis endpoint를 구성했다. `read()`는 예상대로 PostgreSQL 오류를 반환했고 Redis connection
수는 0이었다. 반면 state-store 전체를 mock한 상위 service-contract harness는 PostgreSQL read throw 뒤
valid Redis projection을 반환할 때 HTTP 200과 `redis_old`를 반환했다. 즉 server 선택 로직은 의도대로지만
실제 adapter 생명주기가 계약을 막는다. runtime/DB/Redis mutation 없이 local ephemeral listener와
injected pool만 사용했다.

이 결함 때문에 F-02의 “PostgreSQL read 자체가 실패한 경우 Redis bounded availability fallback”
acceptance는 충족되지 않는다.

### F-03 — `PASS` (in-memory 및 PostgreSQL adapter/SQL 결정적 계약)

독립 harness와 source/SQL 검토 결과는 아래와 같다.

- current Catalog generation과 active embedding generation이 일치하지 않으면 old/new generation
  search와 profile coverage가 모두 빈 결과다.
- vector validation failure는 memory mutation 전에 발생하므로 active pointer와 prior rows를 보존한다.
- projection generation이 build 중 바뀐 상태를 재현하면 replacement가 거부된다.
- 동일 hash의 unchanged row는 다음 generation으로 retain되고 changed row는 새 vector로 교체된다.
- 성공 replacement는 삭제 row를 제거하며 zero inventory는 active pointer를 zero generation으로
  이동하고 vector/profile 결과를 빈 값으로 만든다.
- PostgreSQL transaction failure를 upsert 중 강제하면 `ROLLBACK`이 실행되고 `COMMIT`은 없으며
  client `release()`가 실행된다.
- PostgreSQL replacement SQL은 `BEGIN` 후 projection row를 `FOR UPDATE`하고 upsert/retain/delete/
  active-pointer write 뒤 `COMMIT`한다. row lock 때문에 동시에 진행하는 Catalog projection write는
  commit 경계를 지나기 전 끼어들 수 없고, 이후 current mismatch는 search에서 fail safe한다.
- search와 profile coverage SQL의 alias 및 parameter 순서는 binding, requested generation,
  projection scope, binding-scoped active scope와 일치한다. embedding row, current projection,
  active pointer 세 generation equality가 모두 조건화된다.
- semantic Chat은 active/current mismatch에서 reconcile을 시도하고, 여전히 불일치하면 vector 결과를
  `[]`로 반환한다. embedding path 실패는 bounded current Catalog lexical 검색으로 fallback하며
  삭제된 stale vector candidate를 composer에 전달하지 않는다. query-time incremental stale vector
  priming 경로는 제거됐다.
- warm request performance 회귀는 provider page 0회를 유지해 동기 full inventory scan이 다시
  도입되지 않았음을 확인했다.

실제 PostgreSQL transaction/격리 integration과 실제 embedding provider failure race는 범위상
mutation 없이 수행할 수 없어 `NOT_EXECUTED`이며, 위 판정은 source/in-memory/mock adapter 계약이다.

## Fresh 자동 검증

repository에는 dependency를 설치하거나 symlink하지 않았다. 임시 복사본
`/tmp/datariver-t05-r1-independent.2TK3Dg`에 source를 복사하고, candidate와 기존 dependency
snapshot의 `frontend/package-lock.json` SHA-256이 모두
`1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`임을 확인한 뒤 temporary
copy에만 기존 `node_modules`를 연결했다.

| 검증 | 결과 |
|---|---|
| 기존 전체 `npm run lint` | `PASS` — ESLint zero warning |
| focused ESLint: repair 관련 5개 파일 | `PASS` — zero warning |
| `npm run build:poc` | `PASS` — 기존 `>500 kB` chunk warning만 존재 |
| Node server/provider/chat/performance | `PASS` — 28 passed, 0 failed |
| Catalog workspace/API Vitest | `PASS` — 2 files, 32 passed, 0 failed |
| 독립 F-01/F-02/F-03 harness | `6 passed, 0 failed`; 그중 1개는 실제 adapter Redis fallback 결함의 기대 재현 |
| diff/allowlist/conflict scan | `PASS` |

performance regression 관찰값은 cold HTTP 503 `26.365 ms`, provider 2 pages, warm HTTP 200
`4.727 ms`, provider 0 page, payload 2,861 B, parse `0.053 ms`였다. 이는 deterministic local
harness 값이지 TARGET 성능 승인 수치가 아니다.

## 하드코딩·scope drift 검토

- 새 dependency/package/lockfile, migration/schema/table, service/container/cache/framework: 없음
- backend/T03/T04, UI/CR/IAM 및 history ledger 변경: 없음
- 새 credential literal, secret/log 노출, host/port/timezone hardcoding: 확인되지 않음
- diff scan의 `POC_POSTGRES_PASSWORD` match는 기존 environment-driven constructor를 injected-pool
  guard 안으로 이동하면서 생긴 diff 문맥이며 새 credential 값이나 노출이 아니다.
- DataHub canonical ownership과 current/history 분리: 유지

## NOT_EXECUTED

- active DEV runtime candidate 배포, restart, cache flush, browser timing
- 실제 DataHub/Redis/PostgreSQL/Embedding provider query 또는 mutation
- 실제 PostgreSQL transaction isolation/race integration과 persisted Redis fallback integration
- TARGET load/soak/capacity, TARGET browser, PREP, OPS
- dependency install/change, migration/schema/table, service/container lifecycle
- 제품/테스트/config repair
- merge, push, integration, publication 및 G1/G2/G3/G4 승인

## 결론

F-01 generation completeness와 F-03 current/active vector fence는 독립 재검증을 통과했고 기존
lint/build/Node/Vitest도 모두 통과했다. 그러나 F-02의 실제 state-store adapter에서는 PostgreSQL
read/initialization failure가 Redis 초기화와 read를 선행 차단하므로 명시된 availability fallback을
수행할 수 없다. validation 역할에 따라 repair하지 않았으며 exact candidate는 현재 상태로 독립
승인할 수 없다.
