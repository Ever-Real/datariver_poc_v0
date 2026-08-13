# 영수증: CHANGE-HIST-T05-CURRENT-SYNC-CATALOG-PERFORMANCE

## 계약 및 provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_237785408b13`
- dispatch: `ctx_f8e086a47d52`
- owner role: `40_DATA_AI_KNOWLEDGE` with platform/catalog performance responsibility
- actual model: `gpt-5.6-sol` controlled fallback
- exact base SHA: `7cc7b6a0791add7b91f2d801b3e0650060556045`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- routine heartbeat: disabled
- result SHA: 검증 완료 후 만든 focused local commit SHA를 `worker_done`에 기록한다.

## 최종 판정

- verdict: `PASS`
- measured bottleneck: 활성 DEV 2,000건 Catalog 상세 검색이 60.005732초에 body 없이 timeout
- correction: 기존 PostgreSQL `poc_state`의 atomic current inventory projection과 last-good fallback
- Redis: optional acceleration only
- provider failure: 빈 결과로 변환하지 않고 last-good 또는 cold warming 503
- history/current mixing: 없음
- blocker: 없음
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 변경 경로

- `frontend/poc-server.mjs`
- `frontend/poc-server.providers.test.mjs`
- `frontend/poc-catalog-performance.test.mjs`
- `.orchestration/evidence/CHANGE-HIST-T05-CATALOG-PERFORMANCE.md`
- `.orchestration/receipts/CHANGE-HIST-T05-CATALOG-PERFORMANCE.md`

## 핵심 증거

- before actual DEV:
  - health 0.001037s / root 0.005439s
  - unfiltered 20-item Catalog 0.163218s, 23,825 B, total 2,000
  - filtered Catalog 60.005732s timeout, 0 B
  - 기존 상세 scan은 static 기준 최소 8 DataHub page
  - Redis established connection은 관찰했지만 상세 scan은 Redis/PG inventory를 우회
- after deterministic harness:
  - cold HTTP 503 20.316ms, background 2 provider pages
  - fresh server warm HTTP 200 5.412ms, provider 0 page, 2,861 B, parse 0.049ms
  - Redis failure 시 PostgreSQL last-good 2건 유지
  - partial page failure 시 atomic write 없음, last-good 2건 유지
  - replacement generation에서 삭제된 1건 제거
- validation:
  - focused ESLint `PASS`
  - POC build `PASS`
  - Node server/provider/chat/performance `26 passed`
  - Catalog workspace/API `32 passed`
  - diff/conflict/allowlist `PASS`

상세 측정·정적 추론·`NOT_EXECUTED` 분리는 대응 evidence에 기록했다. credential 값은 읽거나
출력하지 않았다.

## NOT_EXECUTED

- active runtime restart/cache flush/candidate deployment 및 실제 after-runtime 측정
- active Redis counters/values, 정상 PostgreSQL row mutation
- actual browser timing, TARGET load/soak, PREP/OPS
- external mutation, 새 service/container/DB/cache
- backend/T03/T04, UI layout/CR/IAM, dependency/lockfile
- merge, push, integration, publication
- G1/G2/G3/G4 승인
