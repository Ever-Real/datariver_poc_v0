# DEV-FULL-T04 REPAIR-01 Admin/User/System 및 CR Overview 검증

- 선행 완료 commit: `6bd5d5ff0a56fddbefa98ad6a8ad8ec16721672e`
- 선행 제품 SHA: `26807e02b2184aa8b8ed9a2cbc01650199d5537d`
- Control Plane 재검토: 기존 T04 evidence/receipt는 수정하지 않고 후속 증거로 기록한다.
- frozen MCL event/link mutation은 반복하지 않는다.

## 변경 전 runtime 및 authority fence

`2026-08-15T12:53Z` 이후 39083 admin UI/API를 실제 inspection했다. access는 version `3`, users `4`,
systems `2`, schema scopes `2`, assignments `2`, value MD5
`74050e15e3a1b89b6d1686fbabeb82ba`다. frozen event는 선행 작업의 최종 `UNLINKED`/link version `4`를
유지한다.

Admin > 계정/권한 > USERS는 네 access subject를 표시하고 사용자 등록 버튼을 활성화했다. 실제 UI에서
`repair01.user`/`repair01.user@example.test`/viewer를 등록하자 화면에는 즉시 `Repair User`가 추가됐고
성공처럼 dialog가 닫혔다. 그러나 공식 core GET과 access GET은 모두 네 subject만 보존했다. 새로고침하면
`Repair User`가 사라졌다. core만 version `29`, sequence `904`, MD5
`caeb24c0295184fbb5f4c1b7cc294a55`로 증가했고 access는 version `3`/MD5 불변이었다.

## 실제 제품 blocker와 변경 전 acceptance

source inspection 결과 POC Admin adapter의 create user/system/assignment/schema mutation은
`adminMemberships`, `adminSystems`, `adminSystemAssignees`, `adminSystemSchemaScopes`를 browser memory에서
바꾼 뒤 일반 `/poc-api/state/core` PUT을 호출한다. state store는 access document가 존재하면 이 네 필드를
보호하고 현재 값을 보존한다. 따라서 UI가 성공을 표시하지만 authority와 durable state는 바뀌지 않는
실제 제품 결함이다. identity profile/profile role endpoint도 POC adapter에 구현되지 않았지만 `/admin/me`는
관련 operation을 허용한다.

최소 수정 acceptance는 다음과 같다.

1. Admin user create/update/active/role과 system create/schema/assignment responsibility/priority는 모두
   server-held admin이 승인한 공식 access CAS PUT을 사용한다. 일반 core PUT으로 보호 필드를 쓰지 않는다.
2. access users의 profile 표시 필드는 비권위 metadata로만 확장한다. runtime identity, active, role, system,
   exact platform/database/schema, assignment responsibility/priority는 계속 access document가 권위다.
3. unknown/inactive subject와 non-admin의 기존 `401/403`, browser protected claim 거부는 유지한다.
4. UI 성공 후 hard reload와 server recreate에서도 user/system/assignment 값이 보존된다. active/role 변경은
   실제 role pruning과 일치한다.
5. 변경 전 네 access user/system/scope/assignment와 frozen link 원장은 최종 정리에서 원상복구한다.

## CR STATUS OVERVIEW 변경 전 gap

실제 브라우저는 `CR STATUS OVERVIEW`에 10개 column을 렌더링했지만 POC summary adapter가
`overview: []`를 고정해 현재 exact CR이 있어도 empty row를 표시했다. Control Plane 정정에 따른 최종
필수 계약은 정확히 `스키마/시스템/담당자/CR 전체/데이터셋별 미진행/접수완료/재검토/변경·TEST/
완료검토/완료` 10개 column이다.

서버 canonical 5단계 mapping을 그대로 사용한다.

- 접수완료: `REGISTERED`, 최초 회차 `IN_REVIEW` (`REGISTERED`만 pending에도 포함)
- 재검토: `CHANGES_REQUESTED`, 재상신 회차 `IN_REVIEW`
- 변경 / TEST: `TESTING`, `APPLY_QUEUED`, `APPLYING`, `APPLY_FAILED`
- 완료검토: `FINAL_REVIEW`
- 완료: `APPLIED`, `COMPLETED`
- `REJECTED`, `CANCELLED`은 overview total과 모든 5단계 집계에서 제외

POC overview는 active exact schema scope와 server-validated stored CR target/system을 결합하고 browser default
system이나 raw provider inference를 만들지 않아야 한다.

## targeted ESLint 변경 전 gap

test-isolation guard가 사용하는 Node `process`/`URL`은 네 `.mjs` 파일의 global pragma에 의존한다. 명시
Node import 6개(`process` 4, `URL` 2)로 교체한다. 현재 worktree에는 dependency install이 없어 host
target lint가 `@eslint/js` module missing으로 시작하지 못했으며, 검증은 live DB env가 없는 격리
dependency 환경에서 수행한다.

## REPAIR-01 제품 수정

제품 commit `7cf07b1393eedb8368556bc76f0683c720b9784e`은 다음 최소 계약만 구현했다.

- Admin user profile/active/role 및 system/schema/assignment mutation을 공식
  `PUT /api/v1/change-history/access` CAS로 영속화한다.
- access의 subject role/active, system, exact schema scope, responsibility/priority 권위를 유지하고,
  profile 필드는 표시용 metadata로만 사용한다. 일반 core PUT의 protected projection fence는 완화하지
  않는다.
- CR STATUS OVERVIEW는 active exact schema scope와 저장 CR target/system을 결합해 실제 값을 만든다.
  `REJECTED`/`CANCELLED`은 total과 모든 stage에서 제외한다.
- Node test-isolation guard의 `process` 4건과 `URL` 2건을 명시 import로 바꾼다.

최종 UI 계약은 10개 column이다. 제품은 `스키마`, `시스템`, `담당자`, `CR 전체`,
`데이터셋별 미진행`, 그리고 `접수완료/재검토/변경 / TEST/완료검토/완료`의 5단계를 이 순서로
유지한다. Governance UI의 10→9 column 변경은 포함하지 않았다.

## REPAIR-02 IN_REVIEW presentation mapping

제품 commit `4aea6d19c64253130e00d997c2837b74fac4837d`은 domain state를 변경하지 않고
`isResubmittedReviewForOverview` presentation helper와 focused test만 추가했다. `IN_REVIEW`는 다음 중
하나를 만족할 때 재검토로 집계한다.

1. `current_round_number > 1`
2. current round의 `revision_kind = EDITED`
3. current round의 직접 `CHANGES_REQUESTED → IN_REVIEW` transition
4. current round에서 `CHANGES_REQUESTED → REGISTERED` 뒤 다시 `IN_REVIEW`로 들어간 transition evidence

그 외 최초 `IN_REVIEW`는 접수완료다. focused test는 initial false, `EDITED`, resubmission transition,
direct transition을 각각 검증한다.

## 격리 검증

모든 unit test 명령은 PostgreSQL/provider 관련 env를 제거한 격리 환경에서 실행했다. live DB env로 unit
test를 실행하지 않았다.

| 검증 | 결과 |
|---|---|
| explicit Node import 대상 4파일 targeted ESLint | PASS |
| state/server focused Node | PASS `29/29` |
| REPAIR-02 `pocApi.live.test.ts` focused | PASS `17/17` |
| UI/API focused (REPAIR-01) | PASS `56/56` |
| full Node `node --test *.test.mjs` | PASS `71/71` |
| full Vitest, final product SHA | PASS `84 files`, `568/568` |
| full ESLint, final product SHA | PASS |
| TypeScript typecheck | PASS |
| `npm run build:poc` / `npm run build` | PASS / PASS |

Docker image의 OCI revision은 `4aea6d19c64253130e00d997c2837b74fac4837d`다. support service는
재생성하지 않고 39083 web만 rebuild/recreate했으며 최종 container는 healthy다.

## 실제 Admin/User/System runtime E2E

실제 39083 브라우저와 official access CAS에서 아래 순서를 검증했다.

1. UI에서 `repair02.user`를 만들고 profile을 `Repair02Updated User`로 수정했다. official access v5와
   hard reload가 동일 profile을 반환했다.
2. role/active control을 실제 UI에서 inspection했고, nested confirmation 자동화가 안정적으로 열리지 않은
   role/active 실행은 official access API로 수행했다. developer/inactive 변경과 재활성화가 저장 문서에
   반영됐고 hard reload가 비활성/role 표시를 반영했다.
3. UI에서 `RPR02 / Repair02 System`을 생성하고 실제 high-risk confirmation을 승인했다. UI에서
   `repair02.user`의 `DEVELOPER`, priority `2`, active assignment를 추가하고 저장했다. official access v9는
   user `5`, system `3`, scope `2`, assignment `3`과 system version `2`를 반환했다.
4. 39083 web만 강제 recreate한 뒤에도 access v9의 user/profile/system/assignment가 그대로 남았다.

따라서 이전의 “성공처럼 닫히지만 hard reload에서 사라짐” 결함은 수정됐다. browser protected claim이나
core protected projection을 우회하지 않았다.

## Access exact-content 복구

runtime E2E가 끝난 뒤 official access GET v9를 기준으로 임시 `repair02.user`, `RPR02`, 관련 scope와
assignment만 제거해 `If-Match: \"9\"` official PUT을 수행했다. 결과는 access v10이며 users `4`, systems
`2`, scopes `2`, assignments `2`, active subject `checkpoint-admin`이다. version 증가는 CAS 이력으로
허용한다.

PostgreSQL을 read-only로 재확인한 `change-history-access-v1`의 저장 `value::text` MD5는 정확히
`74050e15e3a1b89b6d1686fbabeb82ba`다. 즉 profile metadata를 포함한 임시 fixture가 남지 않았고 원래
access content와 exact 일치한다.

## Phantom core sequence 정리

수정 전 UI의 실패한 memory-only user create는 core version만 올리며 sequence를 선행 정상값 `903`에서
`904`로 증가시켰다. 선행 증거에는 CR 생성 직후 core sequence `903`, CR
`poc-change-request-901 / CR-POC-00902`, round `902`, item `903`이 기록돼 있다. 현재 core에도 유효 ID
최대값은 item `903`이고 새 domain record는 없다.

access 복구 직후 core v36/sequence 904와 CR SHA-256
`c6eeb375814230afb04f5d57af0d9cea1ef1b5966b32fd75cce507b53e2f51ca`를 보존한 뒤, raw SQL이 아닌
official `PUT /poc-api/state/core`로 sequence field만 `903`으로 돌렸다. 결과는 core v37/sequence 903이다.
동일 CR SHA-256과 다음 값은 전후 불변이다.

- ID/number: `poc-change-request-901` / `CR-POC-00902`
- state/version/current round: `REGISTERED` / `1` / `1`
- item: `poc-change-item-903`

## CR STATUS OVERVIEW 실제 브라우저 증거

Orca 내장 브라우저에서 4aea6d1 runtime의 변경관리 화면을 실제 열어 DOM과 accessibility tree를 확인했다.
헤더는 정확히 다음 10개이며 순서도 일치한다.

`스키마 | 시스템 | 담당자 | CR 전체 | 데이터셋별 미진행 | 접수완료 | 재검토 | 변경 / TEST | 완료검토 | 완료`

실제 행은 다음과 같다.

| schema/system | 담당자 | CR 전체 | 미진행 | 접수완료 | 재검토 | 변경/TEST | 완료검토 | 완료 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `oracle / ORCL / semiconductor_seed`, `Checkpoint Oracle` | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `postgres / datariver / semiconductor_seed`, `Checkpoint PostgreSQL` | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |

이는 저장된 `REGISTERED` CR 하나가 total, pending, received에 각각 한 번만 집계되고 Oracle에는 잘못
귀속되지 않음을 보여준다.

## 최종 원장 및 runtime fence

최종 read-only PostgreSQL/API 확인은 다음과 같다.

- canonical checkpoint `a2a280e5d04c…`, partition `0`: first exact `52849`, next `52942`, version `94`
- 보조 checkpoint `62db387b0627…`, partition `0`: first exact `51815`, next `52854`, version `1040`
- semantic ledger `46` rows, distinct identity `46`, distinct normalized transaction `35`
- frozen exact event `ed7a7482…ae23`: `UNLINKED`, primary `null`, candidates `[]`, link version `4`
- frozen link ledger `4` rows, max link version `4`
- canonical/T03B scheduler receipt: 각각 version `1`, successful boundary
  `2026-08-14T15:00:00.000Z`
- web image/runtime revision `4aea6d19c64253130e00d997c2837b74fac4837d`, healthy

frozen MCL/link mutation, raw SQL mutation, test reset, provider mutation, support-service recreate, push는 수행하지
않았다. `datariver_v1`에는 접근하지 않았다.
