# CHANGE-HIST-T07A-CONTRACT 구현 증거

## 범위와 기준

- Task: `CHANGE-HIST-T07A-CONTRACT`
- exact base: `8e6516104de9364157af53e985081da98dae0323`
- 제품 commit: `ef4adbe151901a72d159c8ba565310dc25b4a898`
- 작업 branch/worktree: `Ever-Real/change-hist-t07a-contract`,
  `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t07a-contract`
- 제품 변경은 배정된 여덟 경로에만 한정했다. UI, dependency/lockfile, schema migration,
  service/container/framework, CR state machine은 변경하지 않았다.

## 구현된 최소 계약

1. 기존 repeatable-read PostgreSQL projection에 현재 `sources`와 `checkpoints` 조회만 추가했다.
   새 테이블이나 쓰기 경로는 없으며 ledger/link/access/core/catalog과 같은 snapshot에서 읽는다.
2. 기존 weekly CR 표시 단계 계산을 단일 helper로 옮겨 weekly 집계와 event list/detail의
   `current_stage`가 같은 mapping을 사용한다. CR state, round, revision, approval, transition은
   읽기만 하며 link command 전후 deep-zero-effect assertion을 유지했다.
3. event 응답에 서버 유도 `change_type`, `precision`, `locator`, `allowed_link_actions`를 추가했다.
   `EXACT_MCL`은 DataHub source identity/schema contract, 고정 MCL topic, 동일 partition checkpoint,
   `first_exact_offset <= source_offset < next_offset`가 모두 맞을 때만 제공하고 그 밖에는 `null`이다.
4. `allowed_link_actions`는 viewer/미매핑이면 빈 배열, admin이면 해석된 모든 System, steward/developer면
   현재 동일 책임으로 할당된 System에서만 네 명령을 제공한다. POST의 기존 server authority,
   ETag, idempotency, active subject, CR round/System binding 검사는 그대로 최종 권위다.
5. event list는 authorization pruning 뒤 KST week, change type/category, operation, platform/database/schema,
   System, assignee, primary-link state, CR stage를 적용한 다음 keyset page를 만들고 정확한 visible
   `total`을 반환한다. 기존 KST Monday validator를 weekly와 공유한다.
6. `GET /api/v1/change-history/summary?week_start=`를 추가했다. 권한 범위의 distinct transaction
   schema/metadata/stage 수, event/category/operation/precision 수, catalog source generation/observed time,
   source/checkpoint 기반 capture/sync 상태와 nullable watermark를 반환한다. 저장 근거가 없거나 source가
   없고/여럿이고/checkpoint가 없거나 잘못된 경우 명시 상태와 `null`을 사용하며 `0`, `PASS`, `LIVE`를
   추정하지 않는다.
7. 새 `ChangeHistoryApi`는 summary, list/detail+ETag, weekly, link history, CR reverse history,
   access GET/PUT CAS와 네 link command의 If-Match/Idempotency-Key를 닫힌 TypeScript 타입과 bounded
   runtime parser로 제공한다. 기존 `pocApi.ts` transport는 수정하지 않았다.

## 검증

환경은 macOS arm64, Node `v25.9.0`, npm `11.12.1`이다. `npm ci --no-audit --no-fund`는 기존
lockfile 그대로 368 packages를 설치했고 추적 dependency 파일은 변경되지 않았다.

| 명령 | 결과 |
|---|---|
| `node --test poc-state-store.test.mjs poc-server.test.mjs` | `PASS`, 26/26 |
| `npm run test:poc-server` | `PASS`, 33/33 |
| `npx vitest run --config vitest.config.ts src/features/change-history/changeHistoryApi.test.ts src/poc/pocApi.live.test.ts` | `PASS`, 2 files / 18 tests |
| `npm run lint` | `PASS`, warning/error 0 |
| `npm run typecheck` | `PASS` |
| `npm run build:poc` | `PASS`; 기존 500 kB 초과 chunk advisory만 존재 |
| `git diff --check`와 exact allowlist review | `PASS` |

clean worktree의 최초 focused Node 실행은 dependency 설치 전 `pg` package 부재로 test body 전에
실행되지 않았다. `npm ci` 후 focused server 2/2와 state projection 1/1이 통과했다. 첫 combined Node
실행은 `dist-poc` 생성 전 root 정적 파일이 없어 25/26이었고, `npm run build:poc` 후 동일 명령이
26/26 통과했다. 이는 제품 계약 실패로 숨기지 않고 실행 순서 증거로 기록한다.

추가 회귀는 `CLEAR_PRIMARY`, `REMOVE_CANDIDATE` 실제 성공, `SET_PRIMARY` replay, stale ETag,
idempotency conflict, subject spoof, viewer/할당 role/admin/unmapped action 노출과 CR aggregate 불변을
검증한다. link history의 PostgreSQL bigint도 공개 응답에서 bounded number로 정규화했다.

## 미실행과 gate

- 실제 DataHub/PostgreSQL runtime/provider probe 또는 mutation: `NOT_EXECUTED`
- container/network/volume/process mutation: `NOT_EXECUTED`
- UI 구현과 browser 검증: `NOT_EXECUTED` — 후속 T07B 범위
- push/merge/PREP/OPS/TARGET: `NOT_EXECUTED`
- G1/G2/G3/G4: `NOT_APPROVED`

로컬 source 계약 blocker는 없다. 별도 독립 검증과 T07B 통합 전까지 제품 commit은 candidate다.
