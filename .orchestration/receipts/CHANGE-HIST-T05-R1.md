# 영수증: CHANGE-HIST-T05-R1-REPAIR

## 계약 및 정확 SHA

- run: `run_fe1ea01316d1`
- task: `task_915bb412dec5`
- dispatch: `ctx_2c2e6ef9bc38`
- owner: `40_DATA_AI_KNOWLEDGE Builder`
- exact base / validation evidence head: `15c981beae6006d066744d579f4e3eeee206cf34`
- source candidate under repair: `49528ca50fd0f286d998105b0dbe70c41040caa9`
- exact product repair SHA: `d84456b5b4581f368854a6710656adbaf54bfa7c`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: `NOT_APPROVED`

## 변경 경로

제품 repair commit:

- `frontend/poc-server.mjs`
- `frontend/poc-state-store.mjs`
- `frontend/poc-server.test.mjs`
- `frontend/poc-catalog-performance.test.mjs`

분리된 R1 evidence commit:

- `.orchestration/evidence/CHANGE-HIST-T05-R1.md`
- `.orchestration/receipts/CHANGE-HIST-T05-R1.md`

## 결과

- verdict: `PASS` (builder self-validation)
- F-01: complete/consistent provider total과 final unique cardinality가 일치할 때만 commit;
  premature terminal page는 last-good 유지, valid zero는 commit
- F-02: PostgreSQL configured 시 authoritative read 우선; stale Redis split-success masking 제거
- F-03: 기존 table/state-store만으로 atomic embedding replacement와 current/active generation search
  fence 적용; 실패/부분 refresh 및 삭제 asset은 semantic 결과에서 fail safe
- D-01: prior evidence rewrite 없이 exact product repair SHA를 기록한 R1 evidence/receipt 추가
- dependency/migration/schema/table/service/container/framework 추가: 없음
- blocker: 없음; independent R1 validation은 남아 있음

## 검증 요약

- focused ESLint: `PASS`
- POC build: `PASS` (기존 chunk-size warning)
- Node server/provider/chat/performance: `28 passed / 0 failed`
- Catalog workspace/API Vitest: `32 passed / 0 failed`
- finding-specific negative contracts for F-01/F-02/F-03: `PASS`
- diff/allowlist/conflict/hardcoding/credential review: `PASS`

temporary copy에서만 lock-identical existing dependency snapshot을 연결했다. install이나 repository
symlink/lockfile mutation은 없었다. 최초 static test의 build artifact 누락과 최초 Vitest cwd 오류는
환경 호출을 정정한 뒤 위 최종 결과로 재검증했으며 상세는 evidence에 기록했다.

## NOT_EXECUTED

- active runtime/cache/browser 및 실제 external provider/DB/Redis/Embedding mutation
- 실제 PostgreSQL transaction integration, TARGET/PREP/OPS/load/soak
- dependency/lockfile, migration/schema/table, service/container/framework, backend/T03/T04 변경
- merge/push/integration/publication 및 G1/G2/G3/G4 승인

이 receipt를 포함하는 evidence commit SHA는 자기참조를 피하기 위해 문서 내부에 추정하지 않고,
commit 생성 후 exact SHA를 `worker_done`에 보고한다.
