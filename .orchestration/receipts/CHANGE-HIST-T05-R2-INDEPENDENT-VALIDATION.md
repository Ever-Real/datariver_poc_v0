# 영수증: CHANGE-HIST-T05-R2-INDEPENDENT-VALIDATION

## 계약

- run: `run_fe1ea01316d1`
- task: `task_12cb3fe1bbbb`
- dispatch: `ctx_4ba96585373b`
- owner: `50_QUALITY_VALIDATION`
- exact candidate head: `a34b80347fcd9fff3c09e441e9ccd50fc2637a8f`
- exact product repair: `4e70def39891520b3152bf4cabefa1c46519cbb6`
- compare SHA: `ff595e6bbfd31c32990fcafefc61b50cbd8f1f5d`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: `NOT_APPROVED`

## 허용된 변경

- `.orchestration/evidence/CHANGE-HIST-T05-R2-INDEPENDENT-VALIDATION.md`
- `.orchestration/receipts/CHANGE-HIST-T05-R2-INDEPENDENT-VALIDATION.md`

제품, 테스트, config, dependency, runtime/provider/DB/Redis는 변경하지 않았다. focused local commit은
위 두 문서만 포함한다.

## 판정

- verdict: `FAIL`
- `PASS`: exact clean head/commit separation/allowlist
- `PASS`: PG failure → valid actual Redis last-good HTTP 200
- `PASS`: valid actual PG → Redis connection/GET 0
- `PASS`: PG retry/concurrent startup, Redis concurrent startup, memory isolation
- `PASS`: actual PG unavailable + 연결 가능한 invalid Redis → HTTP 503
- `FAIL`: actual PG unavailable + Redis endpoint unavailable → 1500 ms 내 HTTP 503 없음
- `FAIL`: unavailable Redis startup의 pending reconnect를 bounded close할 state-store surface 없음
- `PASS`: F-01 completeness 및 F-03 current/active generation fence 보존

잔존 finding은 `F-02-R2`다. Redis `connect()`가 실제 연결 불가 상태에서 pending reconnect를 유지하여
`cacheGet()` 및 Catalog request가 provider failure로 수렴하지 않는다. throwing stub 회귀는 통과하지만
actual socket unavailable 경계를 입증하지 못한다.

## Fresh 검증 결과

- focused ESLint: `PASS`
- full ESLint: `PASS`
- POC build: `PASS` (기존 chunk-size warning)
- Node server/provider/chat/performance: `29/29 PASS`
- Catalog workspace/API: `32/32 PASS`
- 독립 boundary harness: 선택 경계 `5/5 PASS`
- actual both-unavailable probe: `FAIL`, `TIMEOUT_AFTER_1500MS`, PG query 1, exit 2
- dependency lock SHA-256: `1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`
- 임시 검증 복사본: `/tmp/change-hist-t05-r2-independent.fQ2Yrw`

관련 표준 회귀 실패가 없고 잔존 failure가 독립 probe로 확정되어, 무관한 frontend 전체 `526` suite는
반복하지 않았다.

## NOT_EXECUTED

- 제품/테스트/config repair
- active runtime/cache/browser 및 실제 external provider/DB/Redis/Embedding mutation
- dependency/lockfile, migration/schema/table, service/container/framework 변경
- frontend 전체 `526`, TARGET/PREP/OPS/load/soak
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge/push/integration/publication 및 G1/G2/G3/G4 승인

이 receipt를 포함하는 validation commit SHA는 자기참조를 피하기 위해 문서에 추정하지 않고,
commit 생성 후 `worker_done`에서 정확히 보고한다.
