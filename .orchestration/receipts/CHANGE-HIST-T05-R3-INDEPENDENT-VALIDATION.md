# 영수증: CHANGE-HIST-T05-R3 독립 검증

## 계약

- run: `run_fe1ea01316d1`
- task: `task_8114edfece40`
- dispatch: `ctx_6e42c5dd5564`
- owner: `50_QUALITY_VALIDATION`
- exact candidate head: `024dbd936c88e8324fda47bd6dc5b25362ff0f98`
- exact product repair: `0424f813443331645701cf24de3308bc552c22d3`
- compare failed validation: `0b88ce47ffdb2320e8429c086dd1078ca0a1301c`
- permission: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`
- G1/G2/G3/G4: `NOT_APPROVED`

## 허용된 변경

- `.orchestration/evidence/CHANGE-HIST-T05-R3-INDEPENDENT-VALIDATION.md`
- `.orchestration/receipts/CHANGE-HIST-T05-R3-INDEPENDENT-VALIDATION.md`

제품, 테스트, config, dependency, runtime/provider/DB/Redis는 변경하지 않았다. focused local validation
commit은 위 두 한국어 문서만 포함한다. 그 commit SHA는 자기참조를 피하기 위해 문서에 추정하지 않고
commit 생성 후 `worker_done`에서 정확히 보고한다.

## 판정

- verdict: `PASS`
- `PASS`: exact clean head, product/evidence commit 분리와 allowlist
- `PASS`: actual PG unavailable + valid Redis URL endpoint unavailable이 `<1500 ms` 내 HTTP `503`
- `PASS`: 같은 endpoint 가동 후 다음 호출이 valid Redis last-good으로 HTTP `200`
- `PASS`: focused actual 경계 3회 반복, lingering process/unhandled rejection 없음
- `PASS`: PostgreSQL readable + Redis unavailable은 PostgreSQL projection 유지
- `PASS`: 양쪽 unavailable/invalid와 valid zero의 의미 구분
- `PASS`: F-01 partial/completeness 및 F-03 active/current generation fence
- `PASS`: 최소 reconnect 변경, validator 비약화, deployment hardcoding/scope drift 없음
- repair performed: `NONE`

## Fresh 검증 결과

- focused ESLint: `PASS`
- full ESLint: `PASS`
- POC build: `PASS` (기존 chunk-size warning)
- Node server/provider/chat/performance: `29/29 PASS`
- Catalog workspace/API: `32/32 PASS`
- focused unavailable/retry actual 회귀: `3/3 PASS`
- dependency lock SHA-256: `1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`
- 임시 검증 복사본: `/tmp/change-hist-t05-r3-independent.0yio5J`
- diff/allowlist/conflict marker/credential/hardcoding review: `PASS`

초기 Vitest 파일 선택 오류로 `PocApp.test.tsx` + `pocApi.live.test.ts`의 `19/19 PASS`만 실행된
artifact는 요구 결과로 계산하지 않았다. 요구된 `CatalogWorkspace.test.tsx` + `pocApi.live.test.ts`를
재실행해 최종 `32/32 PASS`를 확인했다. 관련 failure가 없어 지시대로 전체 무관 526 suite는 실행하지
않았다.

## NOT_EXECUTED

- 제품·테스트·config repair
- active runtime/cache/browser 및 실제 external provider/DB/Redis/Embedding mutation
- dependency install/change, package/lockfile, migration/schema/table, service/container/framework 변경
- frontend 전체 무관 526, backend/UI/CR/IAM, TARGET/PREP/OPS/load/soak
- `/Volumes/SSD_Mac/workspace/datariver_v1` 접근
- merge/push/integration/publication 및 G1/G2/G3/G4 승인

exact candidate는 독립 검증을 통과했다. 이 receipt는 local validation 증거이며 integration 또는 release
승인을 부여하지 않는다.
