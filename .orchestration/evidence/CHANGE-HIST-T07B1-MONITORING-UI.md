# CHANGE-HIST-T07B1-MONITORING-UI 구현 증거

## 범위와 기준

- Task: `CHANGE-HIST-T07B1-MONITORING-UI`
- exact base: `fead4c4f6dfe507359be1c9eccb558518ab33787`
- 제품 commit: `06aeeedc8142254e2b96e1eaaf67e25da9964362`
- 작업 branch/worktree: `Ever-Real/change-hist-t07b1-monitoring-ui`,
  `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t07b1-monitoring-ui`
- 제품 변경은 배정된 Monitoring 다섯 경로에만 한정했다. Change History API/type/server,
  dependency/lockfile, 전역 style, schema/service/CR state와 외부 Monitoring 저장 계약은 변경하지 않았다.

## 구현 결과

1. 내부 고정 ID를 가진 native `데이터 변경현황` 탭을 첫 번째/default active로 추가했다. 이 탭은
   외부 `monitoring_configuration.items`와 분리되어 편집·삭제·재정렬·저장 payload에 들어가지 않고,
   기존 외부 최대 여덟 개 제한도 그대로 외부 항목 수에만 적용된다.
2. 기존 외부 탭 순서, server-returned URL/embed descriptor, sandbox, `no-referrer`, 새 창 fallback,
   명시 높이와 fresh-assurance editor/ETag 저장 동작을 보존했다. 기존 roving-tab keyboard helper에
   native ID를 첫 항목으로 추가해 방향키/Home/End 접근성 계약도 유지했다.
3. native panel은 검증된 `ChangeHistoryApi`만 사용해 주간 summary와 최대 50개 event page를 읽는다.
   KST 현재 날짜로 월요일을 계산하며 고정 주차를 사용하지 않는다. summary는 last successful sync,
   source generation, Schema/Metadata 수, CR 미연결, DataHub/capture sync 상태,
   `history_available_from`, `ledger_guarantee_from`, 닫힌 precision과 주간 stage 수를 표시한다.
4. zero는 숫자 `0`, nullable watermark는 `기록 없음`, server sync 상태는 닫힌 상태 이름의 한국어
   표현, transport/contract 오류는 `ErrorNotice`, event zero는 별도 empty view로 표시해 서로 섞지
   않았다. weekly/schema/metadata/stage만 semantic HTML과 CSS `meter`로 표시하고 서버가 제공하지
   않은 group-by 값을 만들지 않았다.
5. week, change type, category, precision, operation, platform, database, schema, System, assignee,
   CR link state, stage의 열두 필터를 `ChangeHistoryApi.events` query에 전달한다. UI는 이 목록을 다시
   로컬 authority filter하지 않는다.
6. table은 KST `Intl` 시각, precision/category/operation, System, database/schema, asset/entity,
   assignee, CR/stage를 표시한다. `source_occurred_at`이 없을 때만 `detected_at`을 사용하고
   `감지 시각 (detected)`를 행 안에 명시해 발생 시각으로 위장하지 않는다.
7. 기존 `Dialog` 기반 상세 view는 event detail과 CR link history를 함께 다시 읽고, source aspect,
   URN, source/detected/captured 시각, primary/candidate/history와 API가 16 KiB로 검증한 before/after
   semantic JSON을 text node로만 표시한다. link/unlink mutation control과 raw HTML 실행 경로는 없다.
8. capabilities, summary/list, detail/link 요청은 각각 이전 `AbortController`를 취소하고 unmount에서도
   abort한다. refresh/filter/detail은 고정 50개 bound를 넘기지 않으며 stale 응답은 상태에 반영하지
   않는다.

## 검증

환경은 macOS arm64, Node `v25.6.1`, npm `11.9.0`이다. dependency가 없는 clean worktree에서 최초
`npm run typecheck`는 `tsc: command not found`로 test body 전에 실행되지 않았고, 사전 승인된
`npm ci --offline`이 기존 lockfile 그대로 368 packages를 설치한 뒤 모든 필수 gate를 실행했다.

| 명령 | 결과 |
|---|---|
| `npm test -- --run src/features/monitoring/MonitoringPage.test.tsx src/features/monitoring/DataChangeStatusPanel.test.tsx` | `PASS`, 2 files / 13 tests |
| `npm run lint` | `PASS`, warning/error 0 |
| `npm run typecheck` | `PASS` |
| `npm run build:poc` | `PASS`; 기존 500 kB 초과 chunk advisory만 존재 |
| `git diff --check`와 exact allowlist review | `PASS` |

focused test는 native default/keyboard, 외부 iframe/link와 editor payload 회귀, 외부 empty 표시,
summary zero/error/sync 상태, KST 자정 경계의 현재 월요일, 열두 server filter와 limit 50, detected
fallback label, authoritative detail/link history, non-executable markup text, stale request abort를 검증한다.

추가 진단으로 실행한 전체 `npm test`는 acceptance gate가 아니며 `82` files / `541` tests가
통과하고 `5` suites / `1` test가 실패했다. 네 root `.mjs` Node test는 Vitest가 가져와
`No test suite found`로 분류하는 기존 runner-scope 문제이고, `PocApp.test.tsx` 한 건은 POC client가
새 native `/change-history/*` 읽기를 의도대로 live gateway `fetch`에 전달하지만 기존 static navigation
test가 Monitoring 방문도 fetch zero라고 가정해 실패했다. 해당 POC client/test는 배정 경로 밖이므로
완화하거나 숨기지 않았고 후속 소유 범위에서 expectation/fixture를 갱신해야 한다.

## 미실행과 gate

- browser runtime/safe credentialless smoke: `NOT_EXECUTED` — 독립 검증 checkpoint 전 금지 유지
- 실제 DataHub/Timeline/MCL/PostgreSQL/provider probe 또는 mutation: `NOT_EXECUTED`
- container/service/network/volume/process mutation: `NOT_EXECUTED`
- push/merge/PREP/OPS/TARGET: `NOT_EXECUTED`
- G1/G2/G3/G4: `NOT_APPROVED`

할당된 T07B1 source와 필수 gate에는 blocker가 없다. fresh independent validation과 배정 밖 POC
compatibility expectation 정리가 남아 있으며, 이 제품 commit을 production/browser claim으로
승격하지 않는다.
