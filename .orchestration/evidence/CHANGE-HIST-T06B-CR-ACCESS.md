# CHANGE-HIST-T06B CR 접근 API 구현 증거

- 역할: `30_IDENTITY_ACCESS`
- 기준 SHA: `49f7f5c8b1f75e9990a9fb13e4b990b7503d1c61`
- 제품 SHA: `e917bf382e79a672d52636d81b22cedb748d1263`
- 판정: `IMPLEMENTED_POC / REQUIRED_LOCAL_VALIDATION_PASSED`
- 범위: authoritative Node change-history read/link/weekly API와 POC client 전달 계약
- 금지 경계: UI, IAM/OIDC, schema/migration, dependency, service/container, 기존 CR 상태기계 변경 없음

## 구현 결과

1. `GET /api/v1/change-history/events`, event detail, event CR link history 및
   `GET /api/v1/change-requests/{cr_id}/change-history`를 추가했다. 페이지는 권한 pruning 뒤
   `(coalesce(source_occurred_at, detected_at), event_identity)` 순서의 bounded base64url cursor를
   사용하며 기본 50/최대 100이다. 저장소 snapshot은 임의 LIMIT로 잘라 성공시키지 않는다.
2. System은 ledger `asset_urn`과 동일 PostgreSQL repeatable-read snapshot의 current Catalog
   projection `items[].id`를 exact join한 뒤, 서버가 보유한 platform/database/schema와 active
   business System schema scope를 조인한다. DataHub platform 또는 URN 해석을 business System ID로
   대체하지 않는다. catalog projection 부재/오염은 `503`, 미매핑 mutation은 `409`로 fail closed한다.
3. T06A의 server-controlled active subject, role, System, assignment와 priority를 그대로 재사용했다.
   admin/viewer는 open-read 행을 읽고, data_steward/developer는 자신의 active responsibility assignment
   System 행만 읽는다. viewer mutation은 `403`; assigned steward/developer와 admin만 resolve된 System을
   mutation한다. browser identity/role/System/priority/actor/policy/basis/time claim은 거부한다.
4. assignee는 unique minimum-priority active `DATA_STEWARD`, 다음 `DEVELOPER`, 아니면
   `UNASSIGNED`로 계산한다. v1 policy와 `provider_owner_refs`는 authoritative private access document에
   bounded 보존된다. 다만 normalized OWNERSHIP evidence의 reviewed owner-ref 추출 계약이 없으므로
   `DATAHUB_OWNER` fallback을 추측하지 않고 현재는 `UNASSIGNED`로 닫았다.
5. `POST .../cr-link-events`는 typed primary/candidate set/clear/add/remove command,
   `Idempotency-Key`, quoted `If-Match`를 요구한다. Node가 actor/time/policy/basis hash를 생성한다.
   access/core/catalog version+canonical hash, event row, link head를 transaction에서 lock/fence하며,
   idempotency-key advisory lock으로 서로 다른 event의 동시 동일 key도 직렬화한다. exact replay는 200,
   다른 request 재사용과 stale link head는 409다.
6. CR current round, selected System, 모든 current item routing System을 저장 aggregate에서 검증한다.
   link/unlink는 `core.changeRecords`를 쓰지 않으며, transaction 직전 snapshot의 core canonical hash를
   다시 확인한다. 기존 CR state/round/revision/approval/transition/version에는 효과가 없다.
7. `GET /api/v1/change-history/weekly`는 `Asia/Seoul` 월요일 00:00 경계와 source occurred time을 사용해
   권한-pruned distinct normalized transaction을 집계한다. candidate-only, primary 부재/충돌,
   rejected/cancelled/inactive primary CR은 unlinked다. CR stage는 응답 표시 집계일 뿐 상태 전이가 아니다.
8. `pocApi.ts`는 logical change-history 및 CR reverse path를 Node `/api/v1`로 전달하고 signal/body,
   `Idempotency-Key`, `If-Match`, response ETag를 보존한다. browser에서 권한/assignee/weekly를 계산하지 않는다.

## 검증 증거

모든 명령은 `frontend/`에서 제품 SHA 내용으로 실행했다.

| 구분 | 명령 | 결과 |
|---|---|---|
| focused state/server | `node --test poc-state-store.test.mjs poc-server.test.mjs` | PASS, 26/26 |
| focused client adapter | `npx vitest run --config vitest.config.ts src/poc/pocApi.live.test.ts` | PASS, 14/14 |
| full state | `node --test poc-state-store.test.mjs` | PASS, 12/12 |
| full server | `npm run test:poc-server` | PASS, 33/33 |
| lint | `npm run lint` | PASS, 0 warning/error |
| build | `npm run build:poc` | PASS; 기존 500 kB chunk advisory만 출력 |
| whitespace | `git diff --check` | PASS |

테스트는 admin/steward/developer/viewer positive/negative 범위, inactive/unknown subject를 포함한 기존 T06A
계약, exact catalog join, assigned/unassigned pruning, viewer read-only, unmapped mutation, stale ETag,
idempotent replay/conflict, CR binding/zero-effect, reverse lookup, KST weekly와 rejected primary를 확인한다.

## 잔여 한계와 비주장

- 실제 PostgreSQL/DataHub target runtime 통합·부하 검증은 `NOT_EXECUTED`다. local Node tests는 SQL/transaction
  doubles와 HTTP contract로 검증했다.
- 최소 POC read는 완전한 repeatable-read snapshot을 Node에서 집계하여 silent truncation은 없지만,
  대규모 production workload용 SQL pushdown/성능 검증은 후속 범위다.
- reviewed normalized OWNERSHIP owner-ref extraction contract가 없어 `DATAHUB_OWNER` fallback은 활성화하지 않았다.
- G1-G4, production readiness, immutable historical attribution 완전 충족을 주장하지 않는다.

## 변경 경로

- `frontend/poc-state-store.mjs`
- `frontend/poc-state-store.test.mjs`
- `frontend/poc-server.mjs`
- `frontend/poc-server.test.mjs`
- `frontend/src/poc/pocApi.ts`
- `frontend/src/poc/pocApi.live.test.ts`
- `.orchestration/evidence/CHANGE-HIST-T06B-CR-ACCESS.md`
- `.orchestration/receipts/CHANGE-HIST-T06B-CR-ACCESS.json`
