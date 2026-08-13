# DEV-INTEGRATION-CHECKPOINT-01-REPAIR-01 증거

## 판정

- Task: `DEV-CHECKPOINT-01-REPAIR-01`
- 결과: `SUCCEEDED_LOCAL_CANDIDATE`
- 정확한 base SHA: `f37be6fdddcc7c15caac6303defc8f6c9a1bd9ff`
- 제품 commit SHA: `639a4830d7db2775b0932c58adb14ac6185f437c`
- branch: `Ever-Real/dev-checkpoint-01-repair-01-r1`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-checkpoint-01-repair-01-r1`
- 기록 시각: `2026-08-14T04:58:49+09:00`
- 실행 환경: macOS DEV, Node `v25.9.0`, npm `11.12.1`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

지정 base와 clean 상태에서 시작했고 제품 변경은 허용된 `frontend/poc-server.mjs`와
`frontend/poc-catalog-performance.test.mjs` 두 경로에만 한정했다. 새 dependency, service,
container, framework, state-store 또는 deploy 변경은 없다.

## B-01 최소 repair

- DataHub inventory 전체 순회에서 현재 cursor뿐 아니라 응답으로 관찰한 모든 provider cursor를
  집합으로 추적하여 비인접 cycle도 `502`로 fail closed한다.
- 안정된 `total`만큼 unique asset을 관찰했지만 provider가 cursor를 반환하는 정확한 page 경계에서는
  terminal confirmation page를 정확히 한 번 허용한다. 확인 page는 같은 `total`, 새 unique asset 0개,
  후속 cursor 없음 조건을 모두 만족해야 하며, continuation 또는 새 asset은 projection을 쓰지 않고
  `502`로 종료한다.
- cold/no-snapshot refresh 실패 뒤 기존 `retryAt` 전에는 polling이 새 full scan을 시작하지 않고 빠른
  `503`을 반환한다. 단일 in-process refresh promise, PostgreSQL-first atomic projection, last-good,
  optional Redis 및 valid zero 계약은 유지했다.
- source로 확정하지 않은 DataHub 기본 scroll ordering을 가정하지 않았다. 따라서 기존 explicit `urn`
  sort는 이 repair에서 제거하지 않았다.

집중 fixture에서 250개 asset page와 cursor 다음 빈 terminal page는 provider 2회, PostgreSQL write 1회,
Redis best-effort cache write 1회로 완료되고 최종 API가 `200`을 반환했다. terminal continuation,
terminal 새 asset, 비인접 cursor cycle은 모두 `502`이며 write 0회였다. 동시 cold 요청 6개는 한 scan을
공유했고, 실패 후 추가 cold polling 4개는 provider 재호출 없이 모두 정직한 `503`을 반환했다.

## B-02 최소 repair

- server-owned inventory/embedding background promise와 embedding 재실행 timer를 명시적으로 추적한다.
- provider timeout은 유지하고 `AbortSignal.any`로 lifecycle abort를 추가 결합했다. inventory DataHub
  GraphQL과 background embedding 요청만 이 lifecycle signal을 전달받는다.
- `stopPoc()`는 idempotent한 동일 promise를 반환하며, 새 HTTP accept/background launch를 먼저 막고,
  timer를 해제하고, provider work를 abort한 뒤 scheduler/inventory/embedding/HTTP close를 settle하고
  마지막에 state store를 닫는다. CLI signal 경로는 이 단일 종료 계약을 사용한다.
- abort 전 완성되지 않은 inventory는 commit하지 않으며 last-good을 대체하지 않는다. embedding batch도
  abort 확인 뒤에만 generation replacement로 진입하며, stop 이후 timer 재실행과 store 접근을 막았다.

집중 fixture에서 첫 page 뒤 두 번째 provider page가 hang된 startup refresh를 종료했을 때 10초 이내
자연 완료, provider abort 1회, projection write 0회, last-good 보존, state-store close 1회,
post-close store use 0회를 확인했다. 중복 stop은 같은 promise였다. inventory commit 뒤 hang된 embedding도
abort 1회, generation replacement 0회, stop 이후 재실행 0회, post-close store use 0회였다.

## 실행 검증

| 명령 | 결과 |
|---|---|
| `npm ci` | `PASS`; lockfile 변경 없이 368 packages 설치, audit 0 |
| `npm run build:poc` | `PASS`; 기존 500 kB chunk warning만 관찰 |
| `node --test poc-catalog-performance.test.mjs` | `PASS`; 4/4 |
| `npm run lint` | `PASS`; warning 0 |
| `node --test *.test.mjs` | `PASS`; 59/59 |
| `npm test -- --run` | 제품 Vitest 81 files/527 tests는 통과했으나 Node 전용 `node:test` 4 files를 Vitest가 재수집하여 `No test suite found` 4건으로 전체 exit 1 |
| `npx vitest run --config vitest.config.ts --exclude '**/*.test.mjs'` | `PASS`; Vitest 전용 81 files/527 tests |
| `git diff --check` | `PASS` |

혼합 runner exit 1은 제품/test assertion 실패가 아니며, Node 전용 4개 파일은 같은 변경 상태에서
native `node --test *.test.mjs`로 전부 통과했다. Task 범위를 넓히지 않기 위해 Vitest 설정이나 unrelated
test file은 수정하지 않았다.

## 미실행 및 경계

- 기존 39080 listener/provider runtime 접근, 중지, 재시작 또는 변경: `NOT_EXECUTED`
- 실제 DataHub/LLM/provider runtime 검증 또는 mutation: `NOT_EXECUTED`
- container/volume/network lifecycle, PREP, OPS, TARGET, push, merge, rebase, publication: `NOT_EXECUTED`
- state-store/deploy/lockfile 변경: `NOT_EXECUTED`
- G1-G4 승인: `NOT_APPROVED`

이 결과는 task-local source와 fixture 검증을 통과한 local candidate다. 실제 provider 재검증이나 dev 통합
승인을 대신하지 않는다.
