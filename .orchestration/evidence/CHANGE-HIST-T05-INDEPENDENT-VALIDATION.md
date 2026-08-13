# CHANGE-HIST-T05 독립 검증 증거

## 판정과 범위

- 최종 판정: `FAIL`
- owner role: `50_QUALITY_VALIDATION`
- exact candidate source SHA: `49528ca50fd0f286d998105b0dbe70c41040caa9`
- compare base SHA: `7cc7b6a0791add7b91f2d801b3e0650060556045`
- 검증 worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-validation`
- 시작 상태: exact candidate HEAD, clean tree
- 검증 원칙: builder 결론을 신뢰하지 않고 diff, 코드 경로, 기존 회귀 및 임시 독립 harness를 새로 검증했다.
- 제품 source/test/config는 수정하지 않았다. 이 문서와 대응 receipt만 작성했다.
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 후보와 변경 범위 고정

`git diff --name-status 7cc7b6a..49528ca`의 변경 경로는 아래 5개뿐이며 builder Task
allowlist와 일치했다.

- `.orchestration/evidence/CHANGE-HIST-T05-CATALOG-PERFORMANCE.md`
- `.orchestration/receipts/CHANGE-HIST-T05-CATALOG-PERFORMANCE.md`
- `frontend/poc-catalog-performance.test.mjs`
- `frontend/poc-server.mjs`
- `frontend/poc-server.providers.test.mjs`

`git diff --check`, conflict-marker scan 및 시작/종료 status 검사는 `PASS`였다.

## 아키텍처 검토

| 항목 | 판정 | 독립 검토 결과 |
|---|---|---|
| DataHub canonical ownership | `PASS` | local JSON/pgvector는 rebuildable projection으로만 사용하며 provider metadata ownership을 바꾸는 write는 없다. |
| PostgreSQL last-good current read model | `FAIL` | provider terminal page 완전성을 검증하지 않아 불완전 generation을 commit할 수 있고, Redis 값이 valid하면 PostgreSQL 최신 값을 읽지 않는다. |
| Redis optional acceleration | `FAIL` | Redis read 성공/cache write 실패 조합에서 stale Redis projection이 최신 PostgreSQL projection을 가린다. |
| pgvector latest generation only | `FAIL` | semantic search가 active/current generation을 전달하거나 필터하지 않으므로 교체 직후 또는 embedding refresh 실패 중 이전/deleted row를 검색할 수 있다. |
| history/current separation | `PASS` | backend/change-history ledger 경로 변경은 없고 current Catalog adapter 범위에 머문다. |
| synchronous warm full scan 제거 | `PASS` | fresh performance harness에서 warm request의 provider page 수는 0이었다. |

## Findings

### F-01 — `FAIL` — terminal partial provider page가 완전 generation으로 commit됨

`datahubCatalogPage()`는 provider의 `total`을 반환하지만 `startDatahubInventoryRefresh()`는 이를
사용하지 않는다. `nextScrollId`가 없는 순간 수집을 성공으로 간주해 PostgreSQL에 write한다. 따라서
provider가 `total=2`, item 1개, `nextScrollId=null`을 반환하면 partial/malformed provider 결과가
실패로 분류되지 않고 1개짜리 current projection으로 commit된다. 이는 partial provider failure에서
직전 last-good을 유지해야 하는 계약과 삭제 asset replacement 안전성을 위반한다.

임시 복사본의 독립 harness에서 위 응답을 주입했다. cold request는 503 뒤 background write 1회를
실행했고, fresh server는 PostgreSQL에 잘못 저장된 `only_first_of_two` 한 건만 HTTP 200으로 반환했다.
제품 테스트에는 이 terminal-page completeness negative가 없다.

### F-02 — `FAIL` — stale Redis가 최신 PostgreSQL projection을 가림

`storedDatahubInventory()`는 valid Redis 값을 발견하면 즉시 반환하고 PostgreSQL을 읽지 않는다.
refresh 경로는 PostgreSQL write 뒤 Redis `cacheSet()` 실패를 optional failure로 삼는다. 두 경로가
결합되면 PostgreSQL에는 새 generation이 commit됐지만 Redis에는 이전 generation이 남을 수 있고,
fresh process가 이전 generation을 authoritative current처럼 제공한다.

독립 harness에서 Redis에는 `redis_old`, PostgreSQL에는 `postgres_new`를 주입했다. fresh Catalog
request는 `redis_old`만 반환했고 PostgreSQL `read()` 호출 수는 0이었다. 기존 performance test는
Redis get/set을 모두 throw하게 하므로 이 split-success 경로를 검증하지 않는다.

### F-03 — `FAIL` — latest pgvector generation fence가 없음

Catalog replacement commit 뒤 embedding reconcile은 비동기로 예약된다. 그 동안
`searchCatalogEmbeddings()`는 `binding_hash`와 vector dimension만 필터하고 `source_generation` 또는
현재 Catalog generation을 필터하지 않는다. 삭제 대상 row는 reconciliation 마지막 단계에서만
제거된다. 따라서 교체 직후 또는 embedding provider/reconcile 실패 중 semantic Chat이 이전/deleted
asset을 계속 검색할 수 있다. 이는 `pgvector latest only`, deleted asset 비노출 및 embedding
invalidation acceptance를 충족하지 못한다.

이 항목은 source/SQL 경로로 정적 확인했다. 실제 PostgreSQL/Embedding provider mutation은 검증
범위상 실행하지 않았다.

### D-01 — `INSUFFICIENT_EVIDENCE` — builder receipt의 exact result SHA 누락

builder receipt는 result SHA에 실제 값 대신 “검증 완료 후 worker_done에 기록”한다고만 썼고,
builder evidence에도 `49528ca50fd0f286d998105b0dbe70c41040caa9`가 없다. Git commit과 Orca Task
result를 독립 대조해 검증 대상 SHA 자체는 확정했지만, builder 문서 단독 provenance는 불충분하다.

## Fresh 자동 검증

후보 worktree에는 `node_modules`가 없었다. candidate와 DEV integration의 `package-lock.json` SHA-256이
동일함을 확인한 뒤, `/tmp` source 복사본에 기존 unchanged dependency snapshot만 symlink했다.
설치, lockfile 변경 또는 repository symlink는 없었다.

| 검증 | 결과 |
|---|---|
| focused ESLint: server/provider/performance 3개 파일 | `PASS` |
| `npm run build:poc` | `PASS`; Vite chunk-size warning만 존재 |
| Node server/provider/chat/performance | `PASS` — 26 passed, 0 failed |
| Catalog workspace/API Vitest | `PASS` — 32 passed, 0 failed |
| fresh performance harness | `PASS` — cold 503/20.881ms/2 pages, warm 200/4.602ms/0 page/2,861 B, partial HTTP failure last-good 유지, replacement 1건 |
| independent negative harness | `FAIL 재현` — terminal partial commit 및 stale Redis precedence 두 경로 모두 재현 |
| diff/allowlist/conflict/trailing 검사 | `PASS` |

기존 positive regression의 PASS는 위 negative findings를 상쇄하지 않는다.

## 하드코딩·scope drift 검토

- 새 dependency/package/lockfile, service, container, DB, cache, framework 또는 migration: 없음
- backend/T03/T04, CR state, UI layout, IAM 변경: 없음
- 새 credential/secret log 또는 browser 노출: 확인되지 않음
- 새 배포 host/port/timezone hardcoding: 확인되지 않음
- 외부 provider/DB/Kafka 또는 active runtime mutation: 없음

## NOT_EXECUTED

- active runtime candidate 배포, restart, cache flush 및 browser 실제 timing
- active Redis key/value/hit/miss 조회와 실제 PostgreSQL current projection row mutation
- 실제 Embedding/DataHub provider를 사용한 stale/deleted vector race 재현
- TARGET load/soak/capacity, TARGET browser, PREP, OPS
- external provider/DB/Kafka mutation, 새 service/container lifecycle
- 제품/테스트/설정 repair
- merge, push, integration, publication
- G1/G2/G3/G4 승인

## 결론

exact candidate의 기존 lint/build/회귀와 warm request 성능은 통과했다. 그러나 provider terminal-page
완전성, Redis와 PostgreSQL의 최신성 우선순위, pgvector active-generation fence에서 독립 acceptance를
막는 3개 `FAIL`을 확인했다. validation 역할에 따라 repair는 수행하지 않았으며 candidate는 현재
상태로 독립 승인할 수 없다.
