# 영수증: CHANGE-HIST-T05-R1-INDEPENDENT-REVALIDATION

## 계약 및 provenance

- run: `run_fe1ea01316d1`
- task: `task_c36d448dcd51`
- dispatch: `ctx_e922011e6354`
- owner: `50_QUALITY_VALIDATION`
- exact candidate HEAD: `0df91292f0e1a04992fc7227d94084df81092e0b`
- exact product repair SHA: `d84456b5b4581f368854a6710656adbaf54bfa7c`
- compare validation SHA: `15c981beae6006d066744d579f4e3eeee206cf34`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-r1-validation`
- start dirty state: clean, untracked 포함 0건
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: `NOT_APPROVED`

## 변경 경로

- `.orchestration/evidence/CHANGE-HIST-T05-R1-INDEPENDENT-VALIDATION.md`
- `.orchestration/receipts/CHANGE-HIST-T05-R1-INDEPENDENT-VALIDATION.md`

제품 source/test/config는 수정하지 않았다. 위 두 문서만 포함하는 focused local commit을 생성한다.
validation commit SHA는 자기참조를 피하기 위해 문서 안에 추정하지 않고 commit 뒤 `worker_done`에
exact 값으로 보고한다.

## 결과

- verdict: `FAIL`
- F-01: `PASS` — partial/malformed/inconsistent/duplicate/cursor/later-page failure는 commit 0회,
  valid zero만 빈 generation commit
- F-02: `FAIL` — PG 정상 read의 authoritative precedence와 invalid-value fail-safe는 통과했으나,
  실제 state-store는 PG startup/read failure 시 Redis 초기화 전에 실패하고 `cacheGet()`도 같은
  PG start failure를 반복하여 Redis availability fallback에 도달하지 못함
- F-03: `PASS` (결정적 adapter/source 계약) — current/active equality, rollback/release,
  projection race fence, unchanged retention, deletion/zero, profile/search SQL 및 Chat stale exclusion 확인
- blocker: 실제 adapter F-02 결함 1건; validation 역할에서는 repair 금지

## 검증 요약

- 전체 lint: `PASS`
- focused ESLint: `PASS`
- POC build: `PASS` (기존 chunk-size warning)
- Node server/provider/chat/performance: `28 passed / 0 failed`
- Catalog/API Vitest: `32 passed / 0 failed`
- independent harness: `6 passed / 0 failed`; F-02 actual-adapter gap 기대 재현 포함
- diff/allowlist/conflict/provenance/hardcoding review: 완료
- dependency install 및 repository symlink: 없음; lock-identical 기존 snapshot은 `/tmp` copy에만 연결

## NOT_EXECUTED

- active runtime/cache/browser 및 external provider/DB/Redis/Embedding query·mutation
- 실제 PostgreSQL/Redis integration, transaction isolation/race, TARGET/PREP/OPS/load/soak
- dependency/lockfile, migration/schema/table, service/container/framework, backend/UI/CR/IAM 변경
- 제품/테스트/config repair, merge/push/integration/publication 및 G1/G2/G3/G4 승인
