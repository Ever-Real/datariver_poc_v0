# 영수증: CHANGE-HIST-T05-R2-REPAIR

## 계약 및 정확 SHA

- run: `run_fe1ea01316d1`
- task: `task_ddccc6a736e7`
- dispatch: `ctx_ffa6980aa75c`
- owner: `40_DATA_AI_KNOWLEDGE Builder`
- exact base: `ff595e6bbfd31c32990fcafefc61b50cbd8f1f5d`
- R1 product candidate: `d84456b5b4581f368854a6710656adbaf54bfa7c`
- exact R2 product repair SHA: `4e70def39891520b3152bf4cabefa1c46519cbb6`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: `NOT_APPROVED`

## 분리된 변경 경로

제품 repair commit:

- `frontend/poc-state-store.mjs`
- `frontend/poc-server.test.mjs`
- `frontend/poc-catalog-performance.test.mjs`

한국어 evidence commit:

- `.orchestration/evidence/CHANGE-HIST-T05-R2.md`
- `.orchestration/receipts/CHANGE-HIST-T05-R2.md`

## 결과

- verdict: `PASS` (builder self-validation)
- PostgreSQL/Redis lazy startup을 독립시켜 PG startup/read failure 뒤 실제 Redis last-good GET 허용
- readable PostgreSQL은 authoritative이며 broken Redis를 읽지 않음
- invalid PostgreSQL/Redis와 양쪽 unavailable은 HTTP 503, valid zero와 구분
- F-01 completeness 및 F-03 current/active generation fence 유지
- dependency/migration/schema/table/service/container/framework 추가: 없음
- blocker: 없음; fresh independent validation은 남아 있음

## 검증 요약

- 전체 ESLint: `PASS`
- POC build: `PASS` (기존 chunk-size warning)
- Node server/provider/chat/performance: `29 passed / 0 failed`
- Catalog workspace/API Vitest: `32 passed / 0 failed`
- 전체 frontend `src` Vitest 최종 재실행: `526 passed / 0 failed`
- 실제 adapter: HTTP 200, PostgreSQL query 1, fake Redis connection 1 / GET 1
- diff/allowlist/conflict/hardcoding/credential review: `PASS`

lock-identical existing dependency snapshot은 temporary copy에만 연결했고 repository dependency나
lockfile을 변경하지 않았다. 전체 Vitest 최초 호출의 Node-test discovery 오류와 범위 밖 Governance
timing failure는 올바른 범위/단일 재실행/전체 재실행으로 정정했으며 최종 결과는 모두 통과했다.

## NOT_EXECUTED

- active runtime/cache/browser 및 실제 external provider/DB/Redis/Embedding mutation
- 실제 PostgreSQL transaction integration, TARGET/PREP/OPS/load/soak
- dependency/lockfile, migration/schema/table, service/container/framework, backend/UI/CR/IAM 변경
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge/push/integration/publication 및 G1/G2/G3/G4 승인

이 receipt를 포함하는 evidence commit SHA는 자기참조를 피하기 위해 문서 내부에 추정하지 않고,
commit 생성 후 exact SHA를 `worker_done`에 보고한다.
