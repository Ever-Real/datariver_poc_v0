# 영수증: CHANGE-HIST-T02B-ADR-FINALIZE

## 계약

- Task: `CHANGE-HIST-T02B-ADR-FINALIZE`
- Owner role: `10_ARCHITECTURE`
- Preferred model: `GPT-5.6 Sol`
- Actual model: `gpt-5.6-sol`
- Reasoning: `High`
- Exact base SHA: `c1e5d964a8091619ab580ef349d3f13a9d4936cb`
- Result SHA placeholder: `RESULT_SHA_REPORTED_AFTER_FOCUSED_COMMIT`
- 허용 경로:
  - `docs/adr/0123-datahub-change-history-ledger.md`
  - `.orchestration/receipts/CHANGE-HIST-T02B-ADR-FINALIZE.md`

## 결과

- TARGET DataHub `v1.6.0rc1`의 사용자 관찰과 DEV DataHub `v1.6.0`의 직접 관찰을 분리하고,
  TARGET retention/MCL/schema/decode/restart 증거를 `TARGET_RECHECK_REQUIRED`로 유지했다.
- 초기 Timeline 이력은 `BACKFILLED_BEST_EFFORT`, 검증된 forward MCL 사건은 개별
  `EXACT_MCL` precision으로 정했다. `GUARANTEED_FORWARD`는 precision enum이 아니라 첫 성공적으로
  commit된 MCL checkpoint부터의 연속 guarantee scope로 정했다.
- DB checkpoint, deterministic dedup, overlap/replay, restart/catch-up과 Kafka retention 초과 시
  `HISTORY_GAP`을 명시하고 Timeline 복구가 중간 사건을 합성하거나 exact gap을 닫지 못하게 했다.
- 실행 위치를 `CONDITIONAL_EXISTING_WEB_PROCESS_CONTROLLER`로 확정했다. T04 전에 PostgreSQL
  advisory lock과 durable lease/fence, abortable failure isolation, graceful shutdown/restart 검증을
  요구하며 새 container/service를 승인하지 않았다.
- T03 persistence는 `READY`다. T04 DEV 구현은 T03와 lifecycle controls 뒤에만 진행할 수 있고,
  TARGET 활성화는 `BLOCKED_TARGET_RECHECK`다.
- 기존 CR state/revision/approval/target binding과 외부 Monitoring tab 계약을 변경하지 않았다.

## 실행 명령과 검증

- `orca orchestration task-list --run run_fe1ea01316d1 --json`
- `git rev-parse HEAD`, `git status --short --branch`, `git log -5 --oneline --decorate`
- `sed`, `rg`로 Task 계약, 운영 지침, ADR, 최종 DEV probe와 선행 영수증 확인
- allowed-path scan: `PASS`
- `git diff --check`: `PASS`
- conflict marker scan: `PASS`
- focused local commit: `docs: finalize change history capture architecture`

## NOT_EXECUTED

- product code/config/migration/dependency 변경과 product test
- provider/runtime/container/Kafka/data mutation
- 새 service/container 생성
- merge, push, TARGET/PREP/OPS
- G1/G2/G3/G4 승인
