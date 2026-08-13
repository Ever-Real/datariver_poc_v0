# 영수증: CHANGE-HIST-SCHEDULER 독립 검증

## 결과

- 판정: `FAIL`
- finding: `F-01 HIGH` — 오래된 manual boundary가 최신 성공 boundary를 퇴행시킴
- exact base: `4eb9ce95ec45515f5954350b27abf2874c0dd9da`
- product commit: `660d551059e007850ad41ab2773753fe468cf58c`
- evidence head: `04b7eed0612cbe81efe6c56bebfe4a6e57f55815`
- 검증 runtime: Node `v25.9.0`, npm `11.12.1`
- 제품 repair: `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## finding receipt

동일 advisory-lock namespace에서 newer `2026-08-13T15:00:00.000Z` 성공 뒤 older
`2026-08-12T15:00:00.000Z`를 수동 실행한 supplemental probe는 두 호출 모두 `succeeded`, task 2회,
최종 `last_successful_schedule=2026-08-12T15:00:00.000Z`를 관찰했다. 구현은 exact equality만 replay로
건너뛰고 older/newer 비교 또는 monotonic conditional upsert가 없어 multiple-process 직렬화만 제공할 뿐
stale boundary fence를 제공하지 않는다.

최소 repair는 advisory lock 안에서 저장 경계 `>=` 요청 경계를 typed no-op으로 처리하고 receipt
compare/write를 PostgreSQL conditional update로 monotonic하게 만들며 newer→older, exact replay,
multi-process 직렬 경쟁 회귀를 추가하는 것이다. 이번 Task에서는 제품을 수정하지 않았다.

## 검증 receipt

- focused Node test: `PASS 12/12`
- frontend lint: `PASS`
- POC build: `PASS` (기존 chunk-size warning만 존재)
- POC server test: `PASS 28/28`
- lock unavailable: task/receipt 없이 `locked`, client release `PASS`
- capture/reconciliation/receipt failure: 성공 receipt 미기록 `PASS`
- active run stop wait 및 in-process duplicate trigger 병합: `PASS`
- package/lock: 제품 diff 및 검증 mutation 없음
- dependency/framework/service/container/Python/UI/CR state 추가: 없음

## 산출물과 미실행

- 상세 증거: `.orchestration/evidence/CHANGE-HIST-SCHEDULER-VALIDATION.md`
- 본 영수증: `.orchestration/receipts/CHANGE-HIST-SCHEDULER-VALIDATION.md`
- 실제 PostgreSQL contention, Kafka/SR/DataHub, product runtime, Node 22/TARGET: `NOT_EXECUTED`
- merge/push/PREP/OPS/provider/container/DB mutation 및 G1-G4 승인: `NOT_EXECUTED`

local suite가 통과했어도 monotonic/fence 보장이 빠진 correctness finding은 상쇄되지 않는다. 따라서 최종
독립 판정은 `FAIL`이다.
