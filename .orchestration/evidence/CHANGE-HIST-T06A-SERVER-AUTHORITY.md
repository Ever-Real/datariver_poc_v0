# CHANGE-HIST-T06A Node 서버 권위 구현 증거

- 작업: `task_b743aa92f4af`
- 역할: `30_IDENTITY_ACCESS builder`
- exact base: `1818bac1a1b61d8e694d309c030f98998746c8c0`
- 적용한 architecture evidence: `0de84a64ed3fd77b7513e0f89b6f4a3c42f500a0`
- source product commit: `3162c8b798bded6988931a016a9c702863c1c57b`
- 판정: `T06A_IMPLEMENTED / T06B_NOT_IMPLEMENTED`
- 승인 상태: `G1-G4 NOT_APPROVED`

## 1. 구현 범위

기존 `poc_state`만 사용하여 Node 서버가 권위를 갖는 `change-history-access-v1` private scope를
추가했다. 이 scope는 공개 `/poc-api/state/{scope}` allowlist에 넣지 않았다. 활성 subject는
`createPocServer({ activeSubjectId })` 주입값 또는 `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID`에서만
결정하며, 누락·잘못된 타입·주입값과 환경값 충돌은 fail closed한다. request header/query/body의
subject/role/System/responsibility/priority/actor/policy/basis/time claim은 권한 근거로 사용하지 않고
`PROTECTED_CLAIM`으로 거부한다.

`GET/PUT /api/v1/change-history/access`만 추가했다. 최초 PUT은 configured subject와 payload의
`active_subject_id`가 같고 그 사용자가 active `admin`일 때만 `If-Match: "0"`으로 bootstrap한다.
이후 GET/PUT은 현재 저장 문서의 active subject와 server subject가 일치하고 현재 사용자가 active
`admin`일 때만 허용한다. `data_steward`, `developer`, `viewer`는 403, inactive 또는 subject mismatch는
401이다.

PUT 문서는 다음 여섯 필드만 받는다.

- `schema_version`, `active_subject_id`, `users`, `systems`, `system_schema_scopes`,
  `system_assignments`
- role은 `admin|data_steward|developer|viewer`, responsibility는
  `DATA_STEWARD|DEVELOPER` 닫힌 vocabulary다.
- 모든 ID/문자열/배열/priority를 bounded typed 값으로 검증한다.
- subject, System id/code, scope id, assignment tuple의 중복을 거부한다.
- platform은 trim 후 소문자로 정규화하고 database/schema는 bounded trim 값으로 보존한다.
- 하나의 active `(platform, database_name, schema_name)`가 둘 이상의 active System에 매핑되는
  문서를 거부한다.
- inactive/unknown subject 및 unknown/inactive System을 참조하는 active assignment/scope를 거부한다.

## 2. 저장·CAS·projection 경계

access PUT은 private access row와 기존 `core` row를 같은 transaction에서 `ORDER BY scope FOR UPDATE`로
잠근 뒤 두 version을 비교한다. private access version을 quoted ETag/If-Match로 노출하고, server가 읽은
core version도 내부 CAS에 포함하여 동시 core 변경을 stale conflict로 막는다. 메모리 fallback에도 같은
version 비교를 적용했다.

private row에는 active subject/users/assignments를 보관하고, System directory/schema scope는 기존
`core.adminSystems`와 `core.adminSystemSchemaScopes`에 UI-compatible projection으로 유지한다.
`adminMemberships`와 `adminSystemAssignees`도 같은 PUT에서 갱신한다. 기존 core object를 clone한 뒤 이
네 projection 필드만 교체하므로 `changeRecords`와 그 state/round/revision/approval/transition/items 등
CR aggregate에는 effect가 없다.

authority가 존재한 이후 일반 `/poc-api/state/core` PUT은 저장 계층에서 private/core 두 row를 잠그고
`adminMemberships`, `adminSystems`, `adminSystemAssignees`, `adminSystemSchemaScopes`를 현재 권위
projection으로 강제 보존한다. object가 아닌 core 전체 교체도 `CORE_ACCESS_FIELDS_PROTECTED`로
거부한다. 따라서 browser memory는 다른 core POC 상태를 저장할 수 있지만 권위 필드를 덮어쓸 수 없다.

## 3. 변경 파일

- `frontend/poc-state-store.mjs`: private/core read, transactional CAS, generic core overwrite fence
- `frontend/poc-state-store.test.mjs`: memory CAS/fence와 PostgreSQL two-row lock/rollback 검증
- `frontend/poc-server.mjs`: bounded normalization, server subject resolution, admin-only access GET/PUT
- `frontend/poc-server.test.mjs`: bootstrap/role/inactive/spoof/CAS/System mapping/CR zero-effect 회귀

UI, `pocApi.ts`, CR link/query/weekly API, CR state machine, schema/init SQL, migration, dependency/lockfile,
IAM/OIDC, framework, service, container, 환경 파일은 변경하지 않았다.

## 4. 실행 증거

fresh worktree에 `node_modules`가 없어 최초 focused 실행이 `ERR_MODULE_NOT_FOUND: pg`로 중단되었고,
승인된 `npm ci`를 실행했다. lockfile 변경 없이 368 packages 설치, audit 취약점 0건이었다. 이후 아래를
순차 실행했고 모두 성공했다.

1. `node --test poc-state-store.test.mjs`: 11 pass, 0 fail
2. `node --test --test-name-pattern='access|server active subject' poc-server.test.mjs`: 2 pass, 0 fail
3. `node --test --test-name-pattern='dedicated server environment' poc-server.test.mjs`: 1 pass, 0 fail
4. `npm run lint`: exit 0, warning 0
5. `npm run build:poc`: exit 0; Vite build 성공. 기존 500 kB 초과 chunk 경고 1건은 비차단이다.
6. `npm run test:poc-server`: 31 pass, 0 fail
7. `git diff --check`: pass

## 5. 하드코딩·금지 범위 검토

변경 product 두 파일에서 UUID literal을 검색했으며 결과는 0건이었다. 추가 diff에서 T06B
`events`, `weekly`, reverse query, CR link-event route, IAM/OIDC/Keycloak, 새 `CREATE/ALTER TABLE`,
새 `randomUUID()` 사용을 검색했으며 결과는 0건이었다. subject/System/platform 실제값이나 default
identity를 product code에 넣지 않았고, 테스트 fixture 값만 테스트 파일에 존재한다.

## 6. 남은 범위와 승인

T06B의 change-history event list/detail, CR link/unlink, reverse query, weekly aggregate와 모든 UI 변경은
구현하지 않았다. production IAM/RLS/ABAC, 최초 provisioning 운영 절차, 과거 assignment snapshot,
TARGET probe도 이 작업 범위 밖이다. 이 source/local test 결과는 production readiness 또는 gate 승인이
아니며 `G1-G4 NOT_APPROVED`를 유지한다.
