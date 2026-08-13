# CHANGE-HIST-T05 R2 독립 검증 증거

## 판정과 provenance

- 판정: `FAIL`
- 잔존 finding: `F-02-R2` — PostgreSQL과 Redis가 모두 unavailable인 실제 adapter 경로가
  bounded provider failure로 종료되지 않는다.
- Orca run: `run_fe1ea01316d1`
- task / dispatch: `task_12cb3fe1bbbb` / `ctx_4ba96585373b`
- owner role: `50_QUALITY_VALIDATION`
- exact candidate head: `a34b80347fcd9fff3c09e441e9ccd50fc2637a8f`
- exact product repair: `4e70def39891520b3152bf4cabefa1c46519cbb6`
- compare failed validation: `ff595e6bbfd31c32990fcafefc61b50cbd8f1f5d`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

검증 시작 시 worktree는 clean이었고 HEAD가 exact candidate와 일치했다. 제품 repair commit은
`frontend/poc-state-store.mjs`, `frontend/poc-server.test.mjs`,
`frontend/poc-catalog-performance.test.mjs`만 포함하며, 후속 candidate head는 R2 evidence/receipt
두 파일만 포함한다. 이 검증은 제품·테스트·config를 repair하지 않았다.

## 독립 adapter 경계 검증

기존 dependency snapshot과 lock이 동일함을 SHA-256
`1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`로 확인하고,
`/tmp/change-hist-t05-r2-independent.fQ2Yrw` 임시 복사본에서만 독립 harness와 빌드 산출물을
만들었다. repository에는 dependency나 임시 harness를 쓰지 않았다.

| 경계 | 결과 | fresh 관찰 |
|---|---|---|
| PG/Redis 독립 startup | `PASS` | actual PG failure 뒤 actual fake Redis의 valid last-good으로 HTTP 200; 표준 Node 회귀에서 PG query 1, Redis connection 1, GET 1 |
| PG authoritative / Redis 미사용 | `PASS` | actual `createPocStateStore` + `createPocServer`에서 `postgres_new` HTTP 200, fake Redis connection/GET 모두 0 |
| PG retry 및 concurrency | `PASS` | 동시 read 2개가 실패한 startup query 1개를 공유했고 둘 다 reject; 다음 read는 재시작 후 성공; injected pool `end()` 0 |
| Redis concurrency | `PASS` | 동시 cache read 2개가 연결 1개를 공유하고 GET 2개를 정상 처리 |
| invalid Redis fallback | `PASS` | actual PG startup failure + 연결 가능한 Redis의 invalid projection은 HTTP 503, 빈 정상 inventory로 오인하지 않음 |
| both unavailable | `FAIL` | actual PG startup failure + `redis://127.0.0.1:1`에서 Catalog HTTP 요청이 `1500 ms` 내 응답하지 않음; probe 결과 `TIMEOUT_AFTER_1500MS`, PG query 1, exit 2 |
| memory fallback | `PASS` | PG/Redis 미설정 시 instance-local read/write, version 증가, store 간 격리, cache miss `undefined` 확인 |
| close/resource 경계 | `FAIL` | unavailable Redis의 `client.connect()`가 기본 reconnect 상태로 pending이고 state-store에 close surface가 없어 요청/연결 시도를 bounded 종료할 수 없음 |

### F-02-R2 분석

`frontend/poc-state-store.mjs`의 `startRedis()`는 `client.connect()`를 timeout/reconnect bound 없이
await한다. Redis가 연결 거부 상태이면 catch와 `client.destroy()`에 도달하지 않고
`startingRedis`도 pending으로 남는다. 따라서 `storedDatahubInventory()`가 PG read failure 뒤
`cacheGet()`을 await하는 실제 경로는 Redis unavailable을 catch해 provider failure로 바꾸지 못한다.

동시 호출이 한 pending promise/client를 공유하므로 연결 시도 수가 호출 수만큼 즉시 늘지는 않는다.
그러나 request가 bounded 503으로 수렴하지 않고 adapter를 명시적으로 close할 수도 없으므로
요구된 retry/close/availability 경계를 충족하지 않는다. 연결 가능한 Redis가 invalid 값을 반환하는
경로의 503 테스트나 throwing stub의 503 테스트는 이 실제 unavailable socket 경계를 대체하지 못한다.

## F-01/F-03 보존

- `F-01`: incomplete terminal page, later-page failure, valid zero와 last-good 보존 회귀가 Node suite에서
  통과했다. state-store repair는 provider total/cursor completeness 코드를 변경하지 않았다.
- `F-03`: in-memory generation replacement/deletion, invalid vector fail-safe, PostgreSQL
  `FOR UPDATE`/active pointer transaction 및 current/active search fence 회귀가 통과했다. embedding SQL과
  generation 교체 구현은 R2 repair에서 변경되지 않았다.

## Fresh 명령과 결과

| 검증 | 결과 |
|---|---|
| focused ESLint: `eslint poc-state-store.mjs poc-server.test.mjs poc-catalog-performance.test.mjs --max-warnings=0` | `PASS` |
| full ESLint: `npm run lint` | `PASS`; zero warning |
| `npm run build:poc` | `PASS`; 기존 `>500 kB` chunk warning만 존재 |
| Node server/provider/chat/performance 4파일 | `PASS`; `29/29` |
| Catalog workspace/API Vitest 2파일 | `PASS`; `32/32` |
| 독립 state-store boundary harness | `PASS`; 선택된 5개 경계 `5/5` |
| actual both-unavailable bounded probe | `FAIL`; HTTP 503 대신 `TIMEOUT_AFTER_1500MS` |
| diff check, commit allowlist, conflict marker, dependency/credential/hardcoding scan | `PASS` |

관련 표준 회귀에는 실패가 없고 잔존 실패는 독립 actual socket probe로 완전히 재현되므로, 범위 밖
frontend 전체 `526` suite는 지시대로 반복하지 않았다.

## 하드코딩·scope drift 검토

- 새 dependency/package/lockfile, migration/schema/table, service/container/framework: 없음
- backend/UI/CR/IAM 및 `poc-server.mjs` 제품 변경: 없음
- 새 credential literal, secret/log 노출, provider production host/port: 없음
- diff의 loopback과 ephemeral port는 child-process fake adapter test에만 존재한다.
- 환경 기반 PostgreSQL 기본 port/password 줄은 함수 분리 문맥이며 새 credential이 아니다.
- 독립 probe stdout에는 timeout 결과와 PG query count만 있었고 credential/unhandled rejection은 없었다.

## NOT_EXECUTED

- 제품/테스트/config repair
- frontend 전체 무관 `526` suite
- active DEV runtime 배포/restart/cache flush 및 browser timing
- 실제 Redis/PostgreSQL/DataHub/Embedding provider query 또는 mutation
- dependency install/change, lockfile, migration/schema/table, service/container/framework lifecycle
- TARGET load/soak/capacity, PREP, OPS
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge, push, integration, publication 및 G1/G2/G3/G4 승인

## 결론

R2는 PG failure 뒤 valid Redis last-good 복구와 PG authoritative 선택을 고쳤고 F-01/F-03도
보존했다. 하지만 actual Redis endpoint unavailable에서는 startup이 bounded failure로 끝나지 않아
PG/Redis 양쪽 unavailable이 provider failure를 반환해야 한다는 acceptance를 충족하지 못한다.
따라서 독립 판정은 `FAIL`이며 추가 제품 repair와 fresh 독립 재검증이 필요하다.
