# CHANGE-HIST-T05 R2 repair 증거

## 판정과 provenance

- builder 자체 검증 판정: `PASS`
- Orca run: `run_fe1ea01316d1`
- task / dispatch: `task_ddccc6a736e7` / `ctx_ffa6980aa75c`
- owner role: `40_DATA_AI_KNOWLEDGE Builder`
- exact base: `ff595e6bbfd31c32990fcafefc61b50cbd8f1f5d`
- R1 product candidate: `d84456b5b4581f368854a6710656adbaf54bfa7c`
- exact R2 product repair SHA: `4e70def39891520b3152bf4cabefa1c46519cbb6`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-r2`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

validator의 단일 F-02만 repair했다. 제품 commit은 state-store와 두 회귀 테스트 파일만 포함하며,
이 evidence/receipt는 별도 후속 commit으로 분리한다. 기존 F-01 completeness와 F-03 current/active
generation fence 구현은 변경하지 않았다.

## F-02 repair

`createPocStateStore()`의 단일 shared startup promise를 PostgreSQL과 Redis의 독립 lazy startup
상태로 분리했다.

- PostgreSQL read/write 및 Catalog embedding 경로는 PostgreSQL만 시작한다.
- cache get/set/delete 경로는 Redis만 시작한다.
- PostgreSQL startup/read가 실패해도 이후 `cacheGet()`은 PostgreSQL startup을 반복하지 않고
  Redis를 독립 연결해 valid bounded last-good을 읽을 수 있다.
- PostgreSQL이 읽히면 server의 기존 authoritative-first 선택이 그대로 적용되어 Redis를 읽지 않는다.
- Redis 연결 실패는 PostgreSQL 초기화나 readable projection을 정리하거나 가리지 않는다.
- injected pool startup 실패 시 외부 소유 pool을 임의 종료하지 않으며, 제품이 직접 생성한 pool만
  기존과 같이 실패 후 정리한다.
- projection validation과 valid zero 구분은 기존 server 계약을 그대로 사용한다. invalid PostgreSQL
  값은 Redis로 무결성 실패를 가리지 않고, invalid Redis 및 양쪽 unavailable은 HTTP 503으로 fail safe한다.

## 실제 adapter 회귀

`frontend/poc-server.test.mjs`에 fresh child process 기반 회귀를 추가했다. injected PostgreSQL pool은
첫 startup query에서 실패시키고, OS가 할당한 loopback port의 bounded RESP fake Redis가 valid Catalog
projection을 반환하도록 구성했다. active runtime/provider/DB/Redis에는 연결하거나 mutation하지 않았다.

관찰 결과:

- 실제 `createPocStateStore()`와 실제 `createPocServer()` HTTP 경로 사용
- HTTP `200`, item `redis_last_good`
- PostgreSQL query `1`회
- fake Redis connection `1`회, `GET` `1`회
- DataHub provider listener나 external provider 호출 없이 fresh Redis projection만 사용

성능 회귀에는 다음 selection matrix를 추가했다.

- readable PostgreSQL / broken Redis: PostgreSQL `postgres_new` 반환, Redis read `0`
- invalid PostgreSQL / valid Redis: Redis가 무결성 실패를 가리지 않고 HTTP `503`
- failed PostgreSQL / invalid Redis: HTTP `503`
- failed PostgreSQL / failed Redis: HTTP `503`, valid zero로 오인하지 않음

## F-01 및 F-03 비회귀

- F-01: terminal incomplete page와 later-page failure는 last-good을 유지하고, valid zero inventory만
  empty current generation으로 commit하는 기존 performance 회귀가 통과했다.
- F-03: in-memory vector validation failure, generation replacement/deletion, PostgreSQL transaction의
  `FOR UPDATE`/active-pointer commit 및 current/active generation search fence 회귀가 통과했다.
- state-store의 embedding SQL, transaction, active generation pointer 및 server inventory completeness
  코드는 변경하지 않았다.

## Fresh 검증

repository에는 dependency를 설치하거나 `node_modules` symlink를 만들지 않았다. 임시 복사본
`/tmp/change-hist-t05-r2-full.7yMeih`에서만 기존 DEV dependency snapshot을 연결했다. task와 snapshot의
`frontend/package-lock.json` SHA-256은 모두
`1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`였다.

| 검증 | 결과 |
|---|---|
| 전체 `npm run lint` | `PASS` — ESLint zero warning |
| `npm run build:poc` | `PASS` — 기존 `>500 kB` chunk warning만 존재 |
| Node server/provider/chat/performance | `PASS` — `29 passed / 0 failed` |
| Catalog workspace/API Vitest | `PASS` — `2 files / 32 tests` |
| 전체 frontend `src` Vitest 최종 재실행 | `PASS` — `81 files / 526 tests` |
| 실제 PG cold-start failure → Redis adapter fallback | `PASS` — HTTP 200, PG 1 / Redis connect 1 / GET 1 |
| F-02 selection/invalid/unavailable matrix | `PASS` |
| F-01 completeness 및 F-03 generation fence | `PASS` |
| `git diff --check`, allowlist, conflict marker, credential/hardcoding diff scan | `PASS` |

performance harness 관찰값은 cold HTTP 503 `19.746 ms`, provider 2 pages, warm HTTP 200
`4.955 ms`, provider 0 page, payload 2,861 B, parse `0.085 ms`였다. 이는 local deterministic
harness 값이며 TARGET 성능 승인 수치가 아니다.

## 검증 호출 정정 이력

- 추가 전체 Vitest의 첫 무범위 호출은 Node 전용 `poc-catalog-performance.test.mjs`를 Vitest가
  수집해 `No test suite found` 1건으로 종료했다. 해당 파일은 직전 `node --test`에서 통과했다.
- `src`로 바로잡은 첫 전체 실행은 변경 범위 밖 Governance attachment 전환 테스트 1건이 timing
  failure했고 나머지 `525/526`은 통과했다. 그 단일 테스트를 즉시 재실행해 `1/1 PASS`했고,
  전체 `src` 재실행도 최종 `526/526 PASS`했다. 범위 밖 제품/테스트는 수정하지 않았다.

## 하드코딩·scope drift 검토

- 새 dependency/package/lockfile, migration/schema/table, service/container/cache/framework: 없음
- backend/UI/CR/IAM, `poc-server.mjs`, active runtime/provider/DB/Redis mutation: 없음
- 새 credential literal, secret/log 노출, provider-specific production host/port: 없음
- diff의 `127.0.0.1`과 dynamic port는 child-process regression의 bounded local fake socket에만 존재한다.
- 기존 environment-driven PostgreSQL port/password 줄은 함수 분리로 diff 문맥에 다시 나타났을 뿐
  새 값이나 credential 노출이 아니다.

## NOT_EXECUTED

- active DEV runtime 배포/restart/cache flush/browser timing
- 실제 DataHub/Redis/PostgreSQL/Embedding provider query 또는 mutation
- 실제 PostgreSQL transaction isolation/race 및 persisted Redis integration
- dependency install/change, migration/schema/table, service/container/framework lifecycle
- TARGET load/soak/capacity/browser, PREP, OPS
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge, push, integration, publication 및 G1/G2/G3/G4 승인

## 결론

실제 state-store cold-start PostgreSQL failure가 Redis 초기화와 GET을 막던 F-02를 독립 adapter
startup으로 최소 repair했다. PostgreSQL authoritative 선택, invalid-value fail-safe, valid zero 구분,
F-01 completeness 및 F-03 generation fence 회귀가 모두 통과했다. 이 builder 결과는 local candidate
증거이며 독립 acceptance, target runtime 또는 release 승인을 뜻하지 않는다.
