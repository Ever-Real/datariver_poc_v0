# 영수증: CHANGE-HIST-T05-INDEPENDENT-VALIDATION

## 계약 및 provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_55c419a86ea5`
- dispatch: `ctx_24221fd3f533`
- owner role: `50_QUALITY_VALIDATION`
- exact candidate source SHA: `49528ca50fd0f286d998105b0dbe70c41040caa9`
- compare base SHA: `7cc7b6a0791add7b91f2d801b3e0650060556045`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-validation`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- evidence head SHA: 이 receipt와 evidence만 담은 focused commit을 만든 뒤 `worker_done`에 기록한다.

## 최종 판정

- verdict: `FAIL`
- candidate SHA/clean start/allowlist/diff hygiene: `PASS`
- focused ESLint/build: `PASS`
- Node server/provider/chat/performance: `PASS` — 26 passed
- Catalog workspace/API: `PASS` — 32 passed
- independent negative validation: `FAIL` 3건
- builder exact result SHA 문서 증거: `INSUFFICIENT_EVIDENCE`
- blocker: candidate repair와 fresh revalidation 필요; validator는 repair하지 않음
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## Findings

1. `F-01 FAIL`: terminal provider page의 `total` 완전성을 검사하지 않아 partial inventory를
   PostgreSQL current projection으로 commit할 수 있다. 임시 독립 harness로 재현했다.
2. `F-02 FAIL`: valid Redis 값을 PostgreSQL보다 먼저 무조건 반환하므로 Redis write 실패 뒤 stale
   Redis가 최신 PostgreSQL generation을 가릴 수 있다. 임시 독립 harness로 재현했다.
3. `F-03 FAIL`: pgvector 검색에 active/current source-generation fence가 없어 Catalog 교체 직후나
   embedding reconcile 실패 중 이전/deleted asset이 semantic Chat 후보가 될 수 있다.
4. `D-01 INSUFFICIENT_EVIDENCE`: builder evidence/receipt에는 exact result SHA `49528ca...`가 없다.

## 변경 경로

- `.orchestration/evidence/CHANGE-HIST-T05-INDEPENDENT-VALIDATION.md`
- `.orchestration/receipts/CHANGE-HIST-T05-INDEPENDENT-VALIDATION.md`

제품 source/test/config는 변경하지 않았고, 임시 test output은 repository 밖에서만 생성했다.

## NOT_EXECUTED

- active runtime candidate deployment/restart/cache mutation/browser timing
- 실제 Redis/PostgreSQL/Embedding/DataHub mutation
- TARGET load/soak, PREP, OPS
- 제품/테스트/설정 repair
- merge, push, integration, publication
- G1/G2/G3/G4 승인
