# CHANGE-HIST-T05 R3 독립 검증 증거

## 판정과 provenance

- 독립 검증 판정: `PASS`
- Orca run: `run_fe1ea01316d1`
- task / dispatch: `task_8114edfece40` / `ctx_6e42c5dd5564`
- owner role: `50_QUALITY_VALIDATION`
- exact candidate head: `024dbd936c88e8324fda47bd6dc5b25362ff0f98`
- exact product repair: `0424f813443331645701cf24de3308bc552c22d3`
- compare failed validation: `0b88ce47ffdb2320e8429c086dd1078ca0a1301c`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-r3-validation`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

검증 시작 시 worktree는 clean이었고 HEAD가 exact candidate와 일치했다. 제품 commit은
`frontend/poc-state-store.mjs`, `frontend/poc-server.test.mjs` 두 경로만 포함하고, 후속 candidate
evidence commit은 `.orchestration/evidence/CHANGE-HIST-T05-R3.md`와
`.orchestration/receipts/CHANGE-HIST-T05-R3.md` 두 경로만 포함한다. 이 검증에서는 제품·테스트·config를
repair하지 않았다.

## Redis reconnect 최소 변경 검토

제품 변경은 기존 `createPocStateStore()`의 Redis client 생성 옵션에
`socket.reconnectStrategy: false`를 추가하고 연결 실패 정리를 `client.isOpen` 조건으로 제한한 7줄
diff다.

- unavailable endpoint에서 node-redis의 기본 반복 재연결을 사용하지 않아 `connect()`가 terminal
  failure로 수렴한다.
- `startingRedis`는 기존 `finally`에서 해제되므로 같은 store의 다음 호출이 새 client로 재시도할 수 있다.
- 연결 성공 client만 `redis`에 저장되며 PostgreSQL read, memory fallback, generation/embedding 구현은
  수정되지 않았다.
- 새 timeout, 환경 변수, dependency, service, scheduler, migration, schema 또는 framework를 추가하지
  않았다.
- 기존 actual adapter 회귀를 삭제하거나 skip하지 않고 unavailable `503`과 같은 endpoint의 후속 복구를
  추가했다. 명시적 `process.exit(0)`도 제거해 socket/server 정리 후 child process가 자연 종료해야
  PASS하도록 강화했다.

## actual adapter와 availability 경계

fresh Node 실행에서 actual `createPocStateStore()` + `createPocServer()` 회귀가 다음을 검증했다.

1. injected PostgreSQL startup/read 실패와 valid Redis URL의 닫힌 loopback endpoint가 동시에 발생한 첫
   Catalog 요청은 기존 `AbortSignal.timeout(1500)` 경계 안에서 HTTP `503`을 반환했다. 빈 정상
   inventory로 변환되지 않았다.
2. 같은 endpoint에 bounded RESP fake를 가동한 다음 호출은 Redis에 재연결해 valid last-good projection
   `redis_last_good`을 HTTP `200`으로 반환했다. 관찰된 PostgreSQL query는 2회, 성공 Redis connection과
   GET은 각각 1회였다.
3. 위 focused actual 회귀를 별도 Node process로 3회 반복했고 모두 `1/1 PASS`였다. 전체 process duration은
   각각 약 `680 ms`, `695 ms`, `706 ms`였으며 각 실행 내부의 unavailable 응답 `<1500 ms` assertion을
   통과했다.
4. 성공 Redis socket, fake server와 POC HTTP server를 닫은 뒤 명시적 success exit 없이 child process가
   정상 종료했다. lingering reconnect 또는 unhandled rejection은 관찰되지 않았다.

같은 fresh 29-test 묶음의 Catalog performance 경계는 readable PostgreSQL projection이 있으면 Redis
adapter를 호출하지 않고 `POSTGRES_CURRENT_PROJECTION`을 선택하며, PostgreSQL unavailable + valid Redis는
위 actual 회귀에서 last-good을 반환하고, 양쪽 unavailable/invalid는 HTTP `503`으로 fail-safe 처리함을
확인했다. valid zero projection은 `0`건 정상 결과로 유지되어 provider failure와 구분된다.

## F-01/F-03 비회귀

- `F-01`: partial later-page failure, incomplete terminal page, valid zero, last-good 보존 회귀를 포함한
  `poc-catalog-performance.test.mjs`가 통과했다. fresh 관찰값은 partial failure 보존 2건, incomplete
  terminal 보존 1건, valid zero 0건이다.
- `F-03`: in-memory active generation 교체/실패 fence와 PostgreSQL transaction/current-generation SQL
  contract가 `poc-server.test.mjs`에서 통과했다. 제품 diff는 embedding 및 generation 경로를 건드리지
  않았다.
- server/provider/chat 회귀도 함께 통과해 warm request의 기존 current projection 선택과 provider
  fail-safe 의미가 유지됐다.

## Fresh 검증

repository에는 dependency를 설치하거나 `node_modules` 또는 build 산출물을 쓰지 않았다. source를
`/tmp/change-hist-t05-r3-independent.0yio5J`로 복사하고, candidate와 DEV integration의
`frontend/package-lock.json` SHA-256이 모두
`1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`임을 확인한 뒤 기존 unchanged
dependency snapshot을 temporary copy에만 연결했다.

| 검증 | 결과 |
|---|---|
| focused ESLint: state-store/server/performance 3파일 | `PASS`; zero warning |
| 전체 `npm run lint` | `PASS`; zero warning |
| `npm run build:poc` | `PASS`; 기존 `>500 kB` chunk warning만 존재 |
| Node server/provider/chat/performance 4파일 | `PASS`; `29/29` |
| Catalog workspace/API Vitest 2파일 | `PASS`; `32/32` |
| actual unavailable → bounded 503 → 같은 endpoint retry | `PASS`; 전체 묶음 1회와 focused 반복 3회 |
| F-01 completeness / F-03 generation fence | `PASS` |
| commit allowlist, `git diff --check`, conflict/credential/hardcoding scan | `PASS` |

초기 Vitest 호출에서 target 파일 하나를 `CatalogWorkspace.test.tsx` 대신 `PocApp.test.tsx`로 선택해
`19/19 PASS`만 실행한 선택 artifact가 있었다. 이를 요구 검증으로 계산하지 않았으며, 올바른
`CatalogWorkspace.test.tsx` + `pocApi.live.test.ts` 조합을 fresh 재실행해 `32/32 PASS`를 확인했다.
build는 Node suite 전에 완료되어 R3 builder에서 기록한 `dist-poc` setup-order 404는 이번 검증에서
재발하지 않았다.

## 하드코딩·scope drift 검토

- 새 dependency/package/lockfile, migration/schema/table, service/container/framework: 없음
- backend/UI/CR/IAM 및 `poc-server.mjs` 제품 변경: 없음
- 새 credential literal, secret/log 노출, provider production host/port/topic/timezone: 없음
- diff의 `127.0.0.1`, ephemeral port와 `1500 ms`는 bounded local regression에만 존재한다.
- `poc-state-store.mjs`에는 deployment-specific timeout 또는 새 환경 계약이 없다.
- validator 제거, skip, assertion 완화 또는 범위 확장은 확인되지 않았다.

## NOT_EXECUTED

- 제품·테스트·config repair
- frontend 전체 무관 `src` 526 suite
- active DEV runtime 배포/restart/cache flush/browser timing
- 실제 Redis/PostgreSQL/DataHub/Embedding provider query 또는 mutation
- dependency install/change, lockfile, migration/schema/table, service/container/framework lifecycle
- backend/UI/CR/IAM, TARGET load/soak/capacity, PREP, OPS
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge, push, integration, publication 및 G1/G2/G3/G4 승인

## 결론

R3는 F-02-R2의 unbounded Redis startup reconnect를 기존 adapter 경계 안에서 최소 수정했다. 실제 양쪽
state provider unavailable 경로는 bounded explicit provider failure로 끝나고 같은 endpoint의 후속 호출은
Redis last-good으로 복구한다. PostgreSQL authoritative 선택, valid zero 구분, F-01 completeness와 F-03
generation fence도 보존되었다. 따라서 exact candidate에 대한 독립 판정은 `PASS`이며, 이는 local
validation 결과일 뿐 integration, publication 또는 release gate 승인이 아니다.
