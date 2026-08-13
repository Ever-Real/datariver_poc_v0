# 영수증: CHANGE-HIST-T05-R3

## 계약

- run: `run_fe1ea01316d1`
- task: `task_9a2440d35b91`
- dispatch: `ctx_adc3530da6bb`
- owner: `40_DATA_AI_KNOWLEDGE Builder`
- exact base: `0b88ce47ffdb2320e8429c086dd1078ca0a1301c`
- exact product repair: `0424f813443331645701cf24de3308bc552c22d3`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: `NOT_APPROVED`

## 변경 분리

제품 commit `0424f813443331645701cf24de3308bc552c22d3`:

- `frontend/poc-state-store.mjs`
- `frontend/poc-server.test.mjs`

후속 evidence commit:

- `.orchestration/evidence/CHANGE-HIST-T05-R3.md`
- `.orchestration/receipts/CHANGE-HIST-T05-R3.md`

evidence commit SHA는 자기참조를 피하기 위해 이 문서에 추정하지 않고 commit 생성 후 `worker_done`에서
정확히 보고한다. 허용된 다른 product/evidence 경로는 수정하지 않았다.

## 결과

- verdict: `PASS` (`IMPLEMENTED_SELF_VALIDATED_PENDING_INDEPENDENT_REVALIDATION`)
- `PASS`: valid Redis URL endpoint unavailable + PG unavailable이 `<1500 ms` 내 HTTP `503`
- `PASS`: 실패 후 같은 endpoint의 Redis 가동 시 다음 호출이 valid last-good으로 HTTP `200`
- `PASS`: PostgreSQL readable / Redis broken은 PostgreSQL projection을 유지
- `PASS`: 양쪽 unavailable과 valid zero의 의미 구분
- `PASS`: F-01 partial/completeness 및 F-03 active/current generation fence 비회귀
- `PASS`: 실패/성공 socket 정리 뒤 child process clean 종료, unhandled rejection 없음
- architecture deviation / new dependency / blocker: `NONE`

## Fresh 검증 결과

- focused ESLint: `PASS`
- full ESLint: `PASS`
- POC build: `PASS` (기존 chunk-size warning)
- Node server/provider/chat/performance: `29/29 PASS`
- Catalog workspace/API: `32/32 PASS`
- dependency lock SHA-256: `1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`
- 임시 검증 복사본: `/tmp/change-hist-t05-r3.iBaJr7`
- diff/allowlist/conflict marker/credential/hardcoding review: `PASS`

build 전 예비 Node 실행의 root 정적 asset `404` 1건은 임시 복사본에 `dist-poc`이 없어서 발생했고,
build 후 최종 suite는 `29/29 PASS`였다. 관련 product failure가 없어 전체 무관 526 suite는
`NOT_EXECUTED`다.

## NOT_EXECUTED

- active runtime/cache/browser 및 실제 external provider/DB/Redis/Embedding mutation
- dependency install/change, package/lockfile, migration/schema/table, service/container/framework 변경
- frontend 전체 무관 `src` 526, TARGET/PREP/OPS/load/soak
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge/push/integration/publication 및 G1/G2/G3/G4 승인

제품 repair와 builder 검증은 완료되었으며 fresh independent revalidation은 후속 control 단계로 남는다.
