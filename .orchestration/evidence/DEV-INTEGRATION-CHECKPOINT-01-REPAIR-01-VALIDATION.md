# DEV-CHECKPOINT-01-REPAIR-01-VALIDATION 독립 검증 증적

## 범위와 판정

- Task: `DEV-CHECKPOINT-01-REPAIR-01-VALIDATION`
- 역할: `50_QUALITY_VALIDATION`
- 정확한 base SHA: `f37be6fdddcc7c15caac6303defc8f6c9a1bd9ff`
- 제품 commit SHA: `639a4830d7db2775b0932c58adb14ac6185f437c`
- 검증 candidate SHA: `df486d38f80fe58041195d344071335e1fa59edf`
- branch: `Ever-Real/dev-checkpoint-01-repair-01-validation`
- 검증 시각: `2026-08-14T05:11:07+09:00`
- 환경: macOS DEV Mac ARM64, Node `v25.9.0`, npm `11.12.1`
- 판정: `PASS_LOCAL_SOURCE`
- 제품 수정: 없음
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

시작 시 HEAD는 지정 candidate와 정확히 일치했고 worktree는 clean이었다. `base..product`의 변경은
`frontend/poc-server.mjs`, `frontend/poc-catalog-performance.test.mjs` 두 제품 경로뿐이며,
`product..candidate`의 변경은 기존 repair evidence와 receipt 두 경로뿐이다. dependency/lock/deploy/
state-store/service 변경은 없다.

## B-01 정적 독립 검토

- `startDatahubInventoryRefresh()`는 기존 단일 `inventoryRefreshPromise`를 재사용한다.
- provider가 보고한 `total`은 최초 page에서 고정되고 이후 page마다 같은 값인지 확인된다. 모든 응답
  cursor는 `Set`으로 추적되어 즉시 반복뿐 아니라 비인접 cycle도 `502`로 종료된다.
- 관찰한 unique asset 수가 안정된 `total`과 같고 cursor가 남은 경우에만 terminal confirmation 상태로
  전환한다. 바로 다음 page에서 같은 `total`, 새 unique asset 0개, 후속 cursor 없음이 모두 성립해야
  정확히 한 번 commit하며, continuation 또는 새 asset은 commit 전에 `502`로 fail closed한다.
- cold/no-snapshot 경로는 실패 뒤 기존 `inventoryRefreshRetryAt` 이전에 새 scan을 시작하지 않고 빠른
  `503`을 반환한다.
- projection은 전체 검증 뒤 PostgreSQL `write`를 먼저 완료한 다음 in-memory last-good을 교체하고,
  Redis는 best-effort로만 갱신한다. 빈 inventory도 `total=0`, items 0의 검증된 projection으로 처리된다.
- explicit `urn` sort는 source-confirmed 대안 없이 제거되지 않았다. 새 dependency, provider pass-through,
  deployment-specific 제품 상수 또는 validator 완화는 없다.

새 fixture는 250개 exact-boundary page와 빈 terminal page의 2회 provider 호출/1회 PostgreSQL write/
1회 Redis best-effort write/최종 HTTP 200을 확인한다. terminal continuation, terminal 새 asset,
비인접 cursor cycle은 각각 write 0을 확인하며, 동시 cold 요청과 실패 후 `retryAt` 억제도 독립적으로
검증한다.

## B-02 정적 독립 검토

- `providerFetch()`는 기존 timeout signal을 유지하면서 lifecycle signal을 `AbortSignal.any()`로 결합한다.
  해당 lifecycle signal은 server-owned DataHub inventory와 embedding provider 호출에 전달된다.
- inventory promise, embedding promise, embedding 재실행 timer를 명시적으로 소유·추적한다. stop 시작 시
  새 background launch를 차단하고 timer를 제거한 뒤 lifecycle controller를 abort한다.
- `stopPoc()`는 동일 promise를 반환하는 idempotent 계약이다. 새 HTTP accept를 닫고 scheduler, HTTP close,
  inventory, embedding을 `allSettled`로 기다린 뒤 마지막에 state store를 닫는다.
- incomplete page에서 abort된 inventory는 projection을 쓰지 않고 last-good을 보존한다. embedding은 batch와
  generation 교체 전에 abort를 확인하며, stop 뒤 timer 재실행이나 state-store 접근이 없다.
- CLI signal 경로는 별도 force exit 없이 같은 `stopPoc()` 계약을 사용한다. active HTTP request는 server
  close로 drain되고 lifecycle abort는 server-owned background inventory/embedding에 한정된다. 검토 범위에서
  active-request 또는 단일 POC server module lifecycle 회귀는 발견하지 못했다.

새 lifecycle fixture는 hanging 두 번째 inventory page를 abort한 뒤 10초 이내 자연 종료, projection write
0, last-good 보존, state-store close 1회, post-close store use 0, 중복 stop의 동일 promise를 확인한다.
embedding fixture는 provider abort 1회, generation replacement 0, stop 이후 재실행 0을 확인한다.

## 실행 검증

| 명령/검증 | 결과 | 근거 |
|---|---|---|
| fresh `npm ci` | `PASS` | 368 packages 설치, audit 0, lockfile 변경 없음 |
| `npm run lint` | `PASS` | ESLint warning/error 0 |
| `npm run build:poc` | `PASS` | TypeScript/Vite build 완료; 기존 500 kB chunk warning만 관찰 |
| `node --test --test-reporter=tap poc-catalog-performance.test.mjs` | `PASS` | build 후 4/4 통과 |
| `node --test --test-reporter=tap *.test.mjs` | `PASS` | 59/59 통과 |
| `npx vitest run --config vitest.config.ts --exclude '**/*.test.mjs'` | `PASS` | 81 files/527 tests 통과, 51.16초 |
| `npm test -- --run` | `KNOWN_MIXED_RUNNER_COLLISION` | 1회 재현: Vitest가 native `node:test` 파일을 수집해 zero-suite/runner 충돌로 exit 1; 추가 반복하지 않음 |
| allowlist/secret/hardcoding/validator 정적 검토 | `PASS` | 제품 2경로만 변경, test fixture token/loopback URL 외 새 민감값 없음, skip/only/todo 및 assertion 제거 없음 |
| base..product 및 product..candidate `git diff --check` | `PASS` | whitespace/conflict marker 오류 없음 |

fresh install 직후 build artifact가 없는 상태에서 focused 명령을 먼저 실행했을 때 lifecycle 2건은
`Run npm run build:poc before starting the POC server.` precondition으로 실패했고, 순수 B-01 2건은 통과했다.
필수 `build:poc` 완료 후 동일 focused 명령은 4/4, 전체 native Node suite는 59/59 통과했다. 이는 제품
assertion 실패가 아닌 검증 명령 순서 의존성으로 기록하며 범위 밖 test config나 제품 코드는 수정하지 않았다.

## Finding과 미실행 경계

- blocking finding: 없음
- non-blocking product finding: 없음
- 알려진 검증 harness 제약: build artifact 선행 조건과 mixed Vitest/native Node runner 충돌
- 기존 `39080` listener/runtime/provider 접근·중지·재시작·변경: `NOT_EXECUTED`
- 실제 DataHub/LLM provider 검증 또는 mutation: `NOT_EXECUTED`
- container/volume/network lifecycle: `NOT_EXECUTED`
- PREP/OPS/TARGET 검증, push, merge, rebase, publication: `NOT_EXECUTED`
- G1-G4 승인: `NOT_APPROVED`

결론은 `PASS_LOCAL_SOURCE`다. 이는 지정 candidate의 로컬 source/static/fixture 계약만 독립 검증한
결과이며 실제 DataHub runtime, target 환경, 통합 또는 배포 승인을 대신하지 않는다.
