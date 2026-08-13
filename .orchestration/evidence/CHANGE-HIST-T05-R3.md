# CHANGE-HIST-T05 R3 repair 증거

## 판정과 provenance

- builder 자체 검증 판정: `PASS`
- Orca run: `run_fe1ea01316d1`
- task / dispatch: `task_9a2440d35b91` / `ctx_adc3530da6bb`
- owner role: `40_DATA_AI_KNOWLEDGE Builder`
- exact base: `0b88ce47ffdb2320e8429c086dd1078ca0a1301c`
- exact product repair SHA: `0424f813443331645701cf24de3308bc552c22d3`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-r3`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

독립 검증에서 확정된 잔존 finding `F-02-R2`만 repair했다. 제품 commit은
`frontend/poc-state-store.mjs`와 `frontend/poc-server.test.mjs`만 포함하며, 이 evidence/receipt는
별도 후속 commit으로 분리한다. architecture deviation, 새 dependency, migration, service 또는 blocker는 없다.

## F-02-R2 최소 repair

기존 `createPocStateStore()` Redis adapter의 client/config 경계를 그대로 사용하면서 startup client에
`socket.reconnectStrategy: false`를 설정했다. 연결 불가 endpoint에서 Redis client의 기본 무한 재연결이
`connect()`와 `startingRedis`를 계속 pending으로 두던 원인을 제거했다.

- 첫 Redis 연결 실패는 terminal error로 수렴하고 열린 client만 `destroy()`한다.
- `startingRedis`는 `finally`에서 해제되고 `redis`에는 성공적으로 연결된 client만 저장되므로 다음 호출은
  새 client로 재시도할 수 있다.
- Redis는 optional acceleration으로 유지된다. PostgreSQL read 경로와 generation/embedding 경계는
  변경하지 않았다.
- timeout 환경 계약, deployment-specific host/port, 새 close API 또는 별도 scheduler를 추가하지 않았다.

## actual adapter 회귀

기존 actual `createPocStateStore()` + `createPocServer()` child-process 회귀를 같은 ephemeral loopback
endpoint의 `닫힘 -> 가동` 전환으로 확장했다.

1. injected PostgreSQL startup/read가 실패하고 valid Redis URL의 endpoint도 닫힌 첫 Catalog 요청은
   `AbortSignal.timeout(1500)` 경계 안에 HTTP `503`으로 종료한다. 빈 정상 inventory로 변환되지 않는다.
2. 같은 Redis endpoint에 bounded RESP fake를 가동한 다음 호출은 새 Redis client를 생성하고 valid
   last-good projection을 읽어 HTTP `200`과 `redis_last_good`을 반환한다.
3. 관찰된 호출은 PostgreSQL query `2`, 성공 Redis connection `1`, Redis GET `1`이다.
4. fake socket과 HTTP server를 닫은 뒤 child process가 명시적 success `process.exit()` 없이 정상
   종료하므로 실패 client의 lingering reconnect와 unhandled rejection이 없음을 함께 검증한다.

기존 performance selection 회귀도 PostgreSQL readable / Redis broken이면 PostgreSQL projection을
선택하고 Redis read를 수행하지 않으며, 양쪽 unavailable은 HTTP `503`, valid zero는 빈 정상 결과로
구분함을 다시 통과했다.

## F-01/F-03 및 동시성/정리 비회귀

- `F-01`: duplicate/repeated cursor, later-page failure, incomplete terminal page와 valid zero 회귀가 포함된
  Node suite를 통과했다.
- `F-03`: in-memory generation replacement/deletion과 PostgreSQL transaction active-pointer/current-generation
  fence 회귀를 통과했다.
- Redis/PG 독립 startup과 concurrent promise 공유 구현은 수정하지 않았다. 연결 실패 후 promise 해제 및
  후속 재시도는 actual adapter 회귀로 확인했다.
- 성공 fake Redis socket을 닫았을 때 reconnect가 다시 생성되지 않았고 child process가 clean 종료했다.

## Fresh 검증

repository에는 dependency를 설치하거나 `node_modules` symlink를 만들지 않았다. 임시 복사본
`/tmp/change-hist-t05-r3.iBaJr7`에만 기존 DEV dependency snapshot을 연결했다. task와 snapshot의
`frontend/package-lock.json` SHA-256은 모두
`1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`였다.

| 검증 | 결과 |
|---|---|
| focused ESLint: state-store/server/performance 3파일 | `PASS`; zero warning |
| 전체 `npm run lint` | `PASS`; zero warning |
| `npm run build:poc` | `PASS`; 기존 `>500 kB` chunk warning만 존재 |
| Node server/provider/chat/performance 4파일 | `PASS`; `29/29` |
| Catalog workspace/API Vitest 2파일 | `PASS`; `32/32` |
| actual PG+Redis unavailable bounded failure | `PASS`; HTTP `503`, `<1500 ms` assertion |
| 동일 endpoint 후속 Redis retry/last-good | `PASS`; HTTP `200`, connection `1`, GET `1` |
| `git diff --check`, allowlist, conflict/credential/hardcoding scan | `PASS` |

POC build 전 예비 `poc-server.test.mjs` 실행은 정적 `dist-poc`이 없는 임시 복사본에서 root asset이
HTTP `404`여서 `8/9`였고, 새 F-02-R2 actual adapter 회귀는 그 실행에서도 통과했다. 지시된 순서대로
POC build를 생성한 뒤 최종 Node suite를 재실행하여 `29/29`를 확인했다. 제품 defect로 분류하거나 숨기지
않는다. 관련 실패가 남지 않아 지시대로 frontend 전체 무관 `src` 526 suite는 반복하지 않았다.

## 하드코딩·scope drift 검토

- 새 dependency/package/lockfile, migration/schema/table, service/container/framework: 없음
- backend/UI/CR/IAM 및 `poc-server.mjs` 제품 변경: 없음
- 새 credential literal, secret/log 노출, provider production host/port/topic/timezone: 없음
- `127.0.0.1`, ephemeral port와 `1500 ms`는 product config가 아니라 bounded local regression에만 있다.
- `poc-state-store.mjs`에는 새 timeout 값이나 환경 계약을 추가하지 않았다.

## NOT_EXECUTED

- frontend 전체 무관 `src` 526 suite
- active DEV runtime 배포/restart/cache flush/browser timing
- 실제 Redis/PostgreSQL/DataHub/Embedding provider query 또는 mutation
- dependency install/change, lockfile, migration/schema/table, service/container/framework lifecycle
- TARGET load/soak/capacity, PREP, OPS
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge, push, integration, publication 및 G1/G2/G3/G4 승인

## 결론

F-02-R2의 unbounded Redis startup reconnect를 기존 adapter boundary에서 최소 수정했다. 양쪽 state
provider unavailable은 bounded explicit provider failure로 끝나고, 후속 호출은 Redis를 재시도해 valid
last-good을 복구한다. PostgreSQL authoritative 선택, valid zero 구분, F-01 completeness와 F-03
generation fence는 보존되었다. 이 결과는 local builder candidate이며 독립 acceptance나 release 승인이
아니다.
