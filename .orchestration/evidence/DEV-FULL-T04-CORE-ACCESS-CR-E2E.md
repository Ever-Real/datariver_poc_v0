# DEV-FULL-T04 Core 복구·Access·CR 실제 DEV 검증

- 작업 트리: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-recovery-t04`
- 시작 HEAD: `7b7f427a30332b446b8a90b798def7134f90b6ad`
- 통합 제품 SHA: `26807e02b2184aa8b8ed9a2cbc01650199d5537d`
- 통제 fallback: `gpt-5.6-sol high` (`Antigravity` 로그인 재시도 없음)
- 복구 권한: `DEV_BASELINE_RECONSTRUCTION_APPROVED`

## Core 사고 복구 전 보존 증거

`2026-08-15T12:02:19Z`에 live DEV PostgreSQL을 읽기 전용으로 재확인했다. 정확한 version 23
백업은 발견되지 않았으며, 추측한 과거 업무 데이터를 만들지 않는다.

| 항목 | 복구 전 값 |
|---|---|
| `poc_state.core` | version `24`, MD5 `2c5378cd7b1a24e958ae8e23aa83b37a` |
| 사고 payload 표식 | sequence `11`, changeRecords `1`, 첫 ID `request-from-core` |
| `change-history-access-v1` | version `1`, MD5 `74050e15e3a1b89b6d1686fbabeb82ba` |
| 공식 access API | HTTP `200`, ETag `"1"`, SHA-256 `09e58d31634fb9171c45e2d73535524f367e7a9bd62f5f2fa20175ff2d28ded3` |
| access 권위 | active `checkpoint-admin`, users `4`, systems `2`, assignments `2`, schema scopes `2` |
| 보호 core projection | memberships `4`, systems `2`, assignee groups `2`, schema-scope groups `2` |
| 실제 MCL checkpoint | source `a2a280…e34`, partition `0`, first exact `52849`, next `52942`, version `94` |
| ledger | 전체 `46`, fixture `33`, fixture distinct identity `33` |
| CR link event | `0` |
| scheduler receipt | canonical version `1`, T03B isolated version `1` |

보호 projection 배열 MD5는 memberships `a4d5a5b19ab7a262a5b71a4a86670ad4`, systems
`df2e7d9bec0be321f088baca1642f173`, assignees `ecc4b7533f50aa32b398799de95e218a`, schema scopes
`6f89e2fc6dbcc94e1bf042e07005ff9c`다. 이 값과 access version/hash를 공식 core write 전후 fence
불변 기준으로 사용한다.

## 공식 Core baseline 복구

복구 전 증거와 보호 fence를 보존한 뒤 `GET/PUT /poc-api/state/core` 공식 state API만 사용해
추측한 과거 업무 데이터 없이 최소 baseline을 재구성했다. raw SQL `UPDATE`/`DELETE`나 test reset은
사용하지 않았다. 결과는 core version `25`, sequence `900`, changeRecords `0`이며 사고 표식
`request-from-core`가 제거됐다. access version/hash, 네 개 보호 projection MD5, MCL checkpoint/ledger,
CR link, scheduler receipt는 불변이었다.

## 테스트 DB 격리 guard와 strict authority repair

- `ba06c53`에서 Node test context가 상속된 POC PostgreSQL 설정을 Pool 생성 전에 거부하도록 했다.
  명시적 pool double은 허용하고 실제 DB를 쓰는 테스트는 exact target과
  `POC_TEST_DATABASE_ISOLATED_ACK=TRUE`가 함께 있어야 한다.
- Control Plane 정정에 따라 `poc-server.mjs`/test의 schema-only database-empty authority 변경은
  `apply_patch`로 원복했고 별도 repair commit `1fd5142`를 만들었다. 따라서 server authority 계약은
  시작 기준과 동일하게 strict platform/database/schema exact matching을 유지한다.
- DB/provider env를 비운 Node `22.19.0` 격리 이미지에서 state/server focused suite `29/29 PASS`를
  확인했다. live DB env로 unit test를 실행하지 않았다.

## Access 및 Monitoring 실제 runtime 증거

현재 web container와 저장 access document의 active subject는 모두 `checkpoint-admin`이다. 공식 access
API는 HTTP `200`, ETag `"1"`, version `1`이며 users `4`, systems `2`, assignments `2`, exact schema
scopes `2`를 반환했다. 브라우저가 `X-Subject-Id: checkpoint-developer` 또는 query
`subject_id=checkpoint-developer`로 역할을 위조하면 모두 `PROTECTED_CLAIM` HTTP `400`이고 원장 write는
발생하지 않는다.

Orca 내장 브라우저의 Monitoring > 데이터 변경현황에서 다음 서버 필터를 실제 적용했다.

| 필터 | 값 |
|---|---|
| platform / database / schema | `postgres` / `datariver` / `semiconductor_seed` |
| system / assignee | `checkpoint-postgres-system` / `checkpoint-developer` |

UI는 `총 13건`을 표시했고 전부
`urn:li:dataset:(urn:li:dataPlatform:postgres,semiconductor_seed.capital_project_ai_accelerator,DEV)`의
`EXACT_MCL`, `RESOLVED`, `CR 미연결` 이벤트였다. 실제 API도 13건 모두 같은 system/provider context와
DEVELOPER priority `1`, 허용 action
`SET_PRIMARY/CLEAR_PRIMARY/ADD_CANDIDATE/REMOVE_CANDIDATE`를 반환한다. 첫 event
`ed7a74822b684450704efa3672a651a99172e1e64e2f4cdc8b9377af3e94ae23` 상세 UI에서 bounded before/after와
CR primary/candidate/history 없음도 확인했다.

변경 전 제품은 공식 access PUT에서 현재 저장 문서와 새 문서 모두
`active_subject_id == server-held subject`인 active admin을 요구했다. 그 결과 active admin이 공식 API로
active subject를 다른 역할로 회전할 수 없고, 환경 subject만 바꿔 web을 재생성하면 stored mismatch로
`401`이었다. 아래 최소 server 계약 수정 전까지는 비공식 DB 변경이나 authority 완화 없이 이 fence를
보존했다.

### Server-held subject 계약 gap 및 변경 전 acceptance

실제 source diff를 변경 전에 확인했다. `configuredChangeHistorySubject`는 전용 server env/injected 값만
받고 browser protected header/query/body를 별도로 거부하지만, `requireActiveAccessAdmin`과
`changeHistoryActiveUser`가 다시 `document.active_subject_id === subjectId`를 요구한다. 이 두 번째 비교가
저장 metadata를 runtime identity 권위처럼 사용해 정상적인 env-only 순차 recreate를 막는 직접 원인이다.

허용된 변경은 `frontend/poc-server.mjs`와 focused `frontend/poc-server.test.mjs`로 제한하며 acceptance는
다음과 같다.

1. runtime identity는 계속 전용 server-held subject만 사용하고 browser switch/header/query/body spoof는
   기존처럼 거부한다.
2. 저장 access document는 active user, role, exact system scope/assignment 권위를 계속 제공하되
   `active_subject_id`를 runtime subject의 복제 권위로 사용하지 않는다.
3. configured subject가 저장 users에 없거나 inactive면 `401`; access GET/PUT은 configured active admin만
   허용하고 developer/steward/viewer는 `403`을 유지한다.
4. 동일한 저장 document를 두고 server-held env를 admin/developer/steward/viewer로 순차 recreate할 때
   각 역할의 read pruning/action 권한이 적용되며 admin으로 복귀할 수 있다.
5. CAS, core protected projection, exact platform/database/schema mapping 및 provider assignment는 변경하지
   않는다. role60 소유 `pocApi.ts`/test는 수정하지 않는다.

허용된 server 두 파일만 변경한 `e19050ccfd8bae4b96bbb532504ba4345b09d002`에서 DB/provider env를
모두 비운 Node `22.19.0` 격리 container의 `poc-server.test.mjs`가 `14/14 PASS`했다. 이어 Control Plane
승인 `msg_fb2e562c29aa`에 따라 role60 제품 commit
`fe50ac708fd6ac33ef8bb93001e507ceaa339cc1`만 local cherry-pick했다(role60 evidence commit은 미통합).
통합 HEAD는 `26807e02b2184aa8b8ed9a2cbc01650199d5537d`이며 시작 기준 대비 제품 변경은 정확히 다음 6경로다.

- `frontend/poc-state-store.mjs`
- `frontend/poc-state-store.test.mjs`
- `frontend/poc-server.mjs`
- `frontend/poc-server.test.mjs`
- `frontend/src/poc/pocApi.ts`
- `frontend/src/poc/pocApi.live.test.ts`

Monitoring 확인 뒤 DB를 읽기 전용으로 재확인한 결과 core `25`/MD5
`a2c93b4b82dbe54fce7c6f012d3de3f9`, access `1`/MD5 `74050e15e3a1b89b6d1686fbabeb82ba`, ledger
`46` distinct `46`(source별 `33` + `13`), CR link `0`이다. canonical checkpoint는 first `52849`, next
`52942`, version `94`이고 canonical/T03B scheduler receipt는 각각 version `1`이다.

## 역할별 server-held runtime 검증

저장 access 문서의 `active_subject_id`는 계속 `checkpoint-admin`으로 둔 채 web만 server-held env별로
순차 recreate했다. 브라우저 subject switch나 보호 claim은 사용하지 않았다.

| server-held subject | 실제 결과 |
|---|---|
| `checkpoint-admin` | 전체 `46`, exact PostgreSQL `13`, 네 link action 모두 허용, access API `200` |
| `checkpoint-developer` | 할당된 `checkpoint-postgres-system` exact `13`만 노출, Oracle filter `0`, 네 action 허용, access API `403 ACCESS_ADMIN_REQUIRED` |
| `checkpoint-steward` | 할당된 Oracle 범위에 현재 event가 없어 `0`; PostgreSQL event mutation은 `404 CHANGE_HISTORY_EVENT_NOT_FOUND`, link `0` 유지 |
| `checkpoint-viewer` | 전체 `46` read, action 집합은 모두 비어 있음; mutation은 `403 CHANGE_HISTORY_MUTATION_FORBIDDEN`, link `0` 유지 |

공식 admin access PUT으로 viewer를 비활성화했을 때 access `2`, core `26`이 됐고 viewer env recreate는
`401 SUBJECT_UNRESOLVED`였다. admin으로 복귀해 공식 PUT으로 viewer를 복구한 뒤 access `3`, core `27`이
됐으며 users `4` 모두 active, systems `2`, exact schema scopes `2`, assignments `2`가 원래 내용으로
복귀했다. 저장 access value MD5도 `74050e15e3a1b89b6d1686fbabeb82ba`로 복귀했다. 이 검증은 stored
`active_subject_id`를 runtime identity로 쓰지 않으면서 active-user/role/system scope가 계속 권위임을
입증한다.

## role60 제품 통합 및 build 복구

Control Plane 메시지 `msg_fb2e562c29aa`를 받은 뒤 이미 실행 중이던 `e19050c` Docker build background
job을 새로 시작하지 않고 먼저 회수했으며 exit `0`을 확인했다. 그 뒤 role60 제품 commit
`fe50ac708fd6ac33ef8bb93001e507ceaa339cc1`만 충돌 없이 local cherry-pick해
`26807e02b2184aa8b8ed9a2cbc01650199d5537d`를 만들었다. role60 evidence commit은 통합하지 않았다.

통합 candidate image `datariver-poc:local`의 OCI revision은 `26807e02…5537d`이고 `build:poc`은 PASS했다
(chunk-size warning만 존재). 39083 web만 rebuild/recreate했으며 최종 container는 healthy,
server-held subject는 `checkpoint-admin`이다. 시작 SHA 대비 제품 diff는 위의 정확한 6경로뿐이다.

## 실제 UI CR 및 exact-mapped MCL link E2E

role60 search repair 후 UI 카탈로그 검색은 platform/database/schema를 모두 전달했고,
`postgres/datariver/semiconductor_seed`의 exact table asset을 선택할 수 있었다. 실제 UI에서 다음 CR을
생성했다.

| 항목 | 값 |
|---|---|
| CR | `poc-change-request-901` / `CR-POC-00902` |
| 제목 / 상태 / version | `DEV T04 mapped MCL review` / `REGISTERED` / `1` |
| round | `poc-change-round-902`, round `1` |
| item | `poc-change-item-903` |
| selected/target/routing system | 모두 `checkpoint-postgres-system` |
| target asset | `urn:li:dataset:(urn:li:dataPlatform:postgres,semiconductor_seed.capital_project_ai_accelerator,DEV)` |

UI CR 생성으로 core는 version `28`, sequence `903`, MD5
`9d86c9bc09a49af23158c29983b82cfd`가 됐다. 이후 link mutation은 core를 변경하지 않았다.

동일 exact event `ed7a7482…ae23`에 대해 다음 CAS 이력이 append-only로 남았다.

| link version | action | event hash | prior hash | 경로 |
|---:|---|---|---|---|
| 1 | `SET_PRIMARY` | `409a8e0f…fb42` | 없음 | 실제 API, HTTP `201` |
| 2 | `CLEAR_PRIMARY` | `bd27899e…e28f` | `409a8e0f…fb42` | 실제 UI |
| 3 | `ADD_CANDIDATE` | `62c65202…ff06` | `bd27899e…e28f` | 실제 UI |
| 4 | `REMOVE_CANDIDATE` | `ea6d42cb…7df2` | `62c65202…ff06` | 실제 UI |

Primary link 직후 event는 `RECEIVED`, primary CR/round `poc-change-request-901/1`, link version `1`이었고
reverse endpoint는 이 한 event를 반환했다. weekly `2026-08-10` 집계도 total `35`, unlinked `34`,
received `1`이었다. UI unlink 후에는 total/unlinked `35/35`, received `0`으로 복귀했다.

최종 candidate 제거 후 event ETag는
`"ea6d42cba2ad1e68257cd2a5ec349c49262562fb44c76d3f8ebe224316a27df2"`, stage `UNLINKED`,
primary `null`, candidates `[]`, link version `4`다. reverse endpoint는 동일 event 한 건을 현재
`UNLINKED`/version `4`로 반환하고 weekly는 total `35`, unlinked `35`, 이후 단계 모두 `0`이다.

## 최종 불변식 및 결론

- core는 version `28`, sequence `903`, CR 1건(`REGISTERED`, round 1, version 1), MD5
  `9d86c9bc09a49af23158c29983b82cfd`다.
- access는 version `3`, 네 user 모두 active, systems/scopes/assignments 각 `2/2/2`, 저장 value MD5
  `74050e15e3a1b89b6d1686fbabeb82ba`다.
- 보호 core projection MD5는 memberships `a4d5a5b19ab7a262a5b71a4a86670ad4`, systems
  `df2e7d9bec0be321f088baca1642f173`, assignees `ecc4b7533f50aa32b398799de95e218a`, schema scopes
  `6f89e2fc6dbcc94e1bf042e07005ff9c`로 시작 fence와 동일하다.
- ledger는 `46` rows / distinct identity `46` / distinct normalized transaction `35`다. checkpoint는
  `a2a280…e34` first `52849`, next `52942`, version `94`; `62db38…d802` first `51815`, next `52854`,
  version `1040`이다. scheduler receipt 두 개는 각각 version `1`이다.
- exact CR link 원장은 4행을 보존하며 최종 disposition은 유효한 `UNLINKED`다.
- browser spoof 방지, active-user/role/system scope, strict platform/database/schema authority는 모두
  유지됐다. User/Admin API gap은 역할별 `401/403/404`와 admin `200`으로 실제 확인됐고, UI는
  server-held env 순차 recreate 계약에서 동일한 pruning/action 권한을 반영했다.
- live DB env로 unit test를 실행하지 않았고 raw SQL mutation, test reset, provider mutation, push를 하지
  않았다.
