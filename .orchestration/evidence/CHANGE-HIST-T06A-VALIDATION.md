# CHANGE-HIST-T06A 독립 품질 검증 증거

- 작업: `task_81248dc2d018`
- dispatch: `ctx_413e7048670b`
- 역할: `50_QUALITY_VALIDATION`
- 요청 모델: `Gemini 3.1 Pro High~XHigh`
- 실제 모델: `Codex (현재 Orca provider)`
- 위험 등급: `R3 independent validation`
- 검증 시각: `2026-08-14 02:30 KST`
- exact HEAD: `97b88b99b02c679f22f4633193f5db8a45474f27`
- 필수 비교 범위: `1818bac1a1b61d8e694d309c030f98998746c8c0..HEAD`
- 종합 판정: **FAIL**
- 승인 상태: `G1-G4 NOT_APPROVED`

## 1. 범위와 작업 트리

검증 시작 시 HEAD가 요구된 exact SHA와 일치하고 작업 트리가 깨끗함을 확인했다. 비교 범위의
제품 변경은 아래 네 파일뿐이며 전체 diff를 직접 검토했다.

- `frontend/poc-server.mjs`: +392/-7
- `frontend/poc-server.test.mjs`: +221/-0
- `frontend/poc-state-store.mjs`: +164/-0
- `frontend/poc-state-store.test.mjs`: +127/-0

그 밖의 변경은 선행 구현·보수 evidence/receipt 네 파일이다. 이 독립 검증은 제품 소스, 테스트,
validator를 수정하지 않았고 `npm ci`도 lockfile을 변경하지 않았다.

## 2. 정적 권위 경계 검토

다음 요구사항은 코드와 테스트에서 충족됨을 확인했다.

- 활성 subject는 `createPocServer({ activeSubjectId })` 주입값 또는
  `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID`에서만 결정된다. 둘 다 없으면 503, 둘이 충돌하거나
  잘못된 주입 타입이면 401로 fail closed한다. 제품 추가분에 deployment-specific subject/user/
  System/platform/UUID/IP/URL/credential literal은 없다.
- 제품 추가분에는 `DataHub` 문자열이 없고 DataHub를 business System으로 합성하지 않는다.
  business System과 schema mapping은 기존 `core.adminSystems` 및
  `core.adminSystemSchemaScopes`에 투영된다.
- `GET/PUT /api/v1/change-history/access`는 configured subject와 저장 문서의 active subject를
  교차 확인하고 active `admin`만 허용한다. data_steward/developer/viewer는 403, inactive/unknown/
  mismatch subject는 401이며 header/query/body의 보호 claim spoof는 거부한다.
- user/role/System/schema scope/assignment는 exact-key, bounded type, closed vocabulary, 중복,
  활성 참조, 정렬 및 platform 소문자 정규화를 거친다. 하나의 active platform/database/schema가
  둘 이상의 active System에 매핑되는 문서는 거부한다.
- access PUT은 quoted `If-Match`를 요구하고 access/core 두 version을 쓰기 transaction에서 다시
  검사한다. stale access 또는 동시 core 변경은 409이며 실패 transaction은 rollback한다.
- private access authority가 생긴 뒤 generic core PUT은 `adminMemberships`, `adminSystems`,
  `adminSystemAssignees`, `adminSystemSchemaScopes`를 저장 계층에서 보존한다. access projection은
  기존 core 객체를 clone한 뒤 이 네 필드만 교체하므로 `changeRecords`의 state/round/revision/
  approval/transition을 변경하지 않는다.
- PostgreSQL의 generic core 최초 생성과 access 최초 생성 양 경로가 모두 `BEGIN` 다음 동일한
  `pg_advisory_xact_lock(hashtextextended('change-history-access-v1', 0))`을 획득하고 그 뒤에 row
  `SELECT ... ORDER BY scope FOR UPDATE`를 실행한다. 따라서 row가 모두 없는 최초 경쟁도 동일 key로
  직렬화되고, 뒤늦은 access CAS는 새 version을 보고 stale rollback한다.
- 새 table/schema, dependency/lockfile, service/container, IAM/OIDC/Keycloak, 배포 env 변경은 없다.
  제품 추가분의 logging marker와 credential-value marker도 0건이며 access document를 log하는
  경로가 없다.

## 3. 실행 결과

로컬 도구는 Node `v25.9.0`, npm `11.12.1`이었다. `frontend/node_modules`가 없어 먼저
`npm ci --no-audit --no-fund`를 실행했고 368 packages를 설치했다. 이후 요구된 순서를 유지했다.

| 순서 | 명령 | 결과 |
|---:|---|---|
| 1 | `npm ci --no-audit --no-fund` | PASS, 368 packages 설치, exit 0 |
| 2 | `node --test poc-state-store.test.mjs` | PASS, 11/11 |
| 3 | `npm run build:poc` | PASS, exit 0; 500 kB 초과 chunk 경고 1건 |
| 4 | `node --test poc-server.test.mjs` | PASS, 12/12 |
| 5 | `npm run lint` | **FAIL**, 3 errors, 0 warnings, exit 1 |
| 6 | `npm run build:poc` | PASS, exit 0; 같은 비차단 chunk 경고 |
| 7 | `npm run test:poc-server` | PASS, 31/31 |
| 8 | `git diff --check 1818bac1...HEAD` | PASS |

## 4. 실패 상세

`npm run lint`가 아래의 이번 변경 추가분 3건을 검출했다.

1. `frontend/poc-server.mjs:326:53` — `no-control-regex`
2. `frontend/poc-server.mjs:333:62` — `no-control-regex`
3. `frontend/poc-server.test.mjs:570:34` — `no-undef` (`structuredClone`)

앞의 두 건은 access 문자열 검증 정규식의 control-character range이고, 마지막 한 건은 새 CR
zero-effect 회귀 테스트의 전역 사용이다. 빌드와 런타임 테스트는 모두 통과했지만 repository lint
gate가 exit 1이므로 선행 evidence의 “lint exit 0” 주장과 현재 exact HEAD의 fresh 실행 결과가
일치하지 않으며, 이 독립 검증은 종합 **FAIL**로 판정한다. 제품 수정 금지 때문에 보수는 수행하지
않았다.

## 5. 환경별 판정과 남은 작업

- LOCAL SOURCE: **FAIL** — 기능/빌드/정적 권위 검토는 통과했으나 lint 3건이 차단한다.
- PREP: `NOT_EXECUTED`
- OPS: `NOT_EXECUTED`
- TARGET: `NOT_EXECUTED`
- 배포 runtime: `NOT_EXECUTED`

후속 제품 소유자는 위 lint 3건을 validator 약화 없이 보수하고 동일 순서의 전체 게이트를 다시
실행해야 한다. 이 결과는 push/merge, PREP/OPS/TARGET 작업, production readiness 또는 gate 승인을
포함하지 않으며 `G1-G4 NOT_APPROVED`를 유지한다.
