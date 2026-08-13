# CHANGE-HIST-T06A 독립 재검증 증거

- 작업: `task_717d0df10b37`
- 역할: `50_QUALITY_VALIDATION`
- 검증 시각: `2026-08-14 02:58 KST`
- exact candidate SHA: `62ef5c7c588f778c4b7b0994ac50387dfd598d84`
- REPAIR-02 product commit: `7da591b55a43e01beca5ca9c9e38d8993105db17`
- 이전 실패 검증 대상 SHA: `97b88b99b02c679f22f4633193f5db8a45474f27`
- T06A 비교 기준 SHA: `1818bac1a1b61d8e694d309c030f98998746c8c0`
- 종합 판정: **PASS_LOCAL_SOURCE / INDEPENDENT_VALIDATION_PASS / PENDING_T09_AUDIT**
- 승인 상태: `G1-G4 NOT_APPROVED`

## 1. 범위와 provenance

시작 시 HEAD가 지정된 exact candidate SHA와 일치하고 작업 트리가 clean임을 확인했다. 제품 소스와
테스트는 수정하지 않았으며, 이 문서와 대응 receipt만 작성했다. Orca의
`dispatch-show --task task_717d0df10b37` 결과는 dispatch가 `null`이었으므로 dispatch 식별자를
생성하거나 완료 신호를 꾸며내지 않는다. 검증 결과의 Orca lifecycle 반영은 Control Plane이
별도로 처리해야 한다.

`97b88b99...HEAD`의 제품 diff는 아래 두 파일뿐이다.

- `frontend/poc-server.mjs`: control-character 정규식 2곳을 공통 code-point predicate로 교체
- `frontend/poc-server.test.mjs`: plain CR fixture의 전역 `structuredClone`을 JSON deep clone으로 교체

그 밖의 해당 범위 변경은 이전 실패 검증 및 REPAIR-02 evidence/receipt다. package/lockfile,
ESLint 설정, disable 주석, schema, service, container, UI 및 T06B 변경은 없다.

## 2. REPAIR-02 독립 검토

`hasAccessControlCharacter`는 문자열을 Unicode code point 단위로 순회하여 `U+0000-U+001F` 또는
`U+007F`만 거부한다. 기존 두 정규식의 금지 범위와 동일하며 `accessString`의 trim·비어 있음·최대
길이 검사 및 `accessOptionalString`의 길이·trim 계약도 유지된다. ESLint rule, validator 또는 테스트
assertion을 완화한 변경은 없다.

테스트의 `changeRecords`는 JSON-compatible plain fixture이므로
`JSON.parse(JSON.stringify(...))`가 기존 deep-copy 목적을 유지한다. production의
`structuredClone(currentValue)`는 건드리지 않았고, access 갱신 전후 CR zero-effect 비교도 그대로다.
fresh `npm run lint`가 warning 없이 성공하여 이전 `no-control-regex` 2건과 `no-undef` 1건이 해소됨을
확인했다.

## 3. T06A 전체 권위·동시성 경계 검토

- 활성 subject는 서버 주입 `activeSubjectId` 또는 `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID`에서만
  결정된다. 누락은 503, 잘못된 값이나 주입/환경 충돌은 401로 fail closed하며 request의
  subject/role/System/responsibility/priority/actor/policy/time claim을 권위 근거로 사용하지 않는다.
- private `change-history-access-v1` scope는 generic state allowlist에 노출되지 않는다.
  `GET/PUT /api/v1/change-history/access`는 저장된 active subject와 서버 subject를 교차 확인한 뒤
  active admin만 허용한다. non-admin은 403, inactive/unknown/mismatch는 401이다.
- user/role/System/schema scope/assignment 입력은 exact key, bounded type, closed vocabulary,
  활성 참조, 중복과 ambiguous active mapping을 검증한다. DataHub platform을 business System으로
  합성하지 않고 기존 `adminSystems`/`adminSystemSchemaScopes` projection을 사용한다.
- access PUT은 quoted `If-Match`와 access/core version을 사용한다. PostgreSQL write transaction은
  `BEGIN` 직후 동일 key의 `pg_advisory_xact_lock(hashtextextended($1, 0))`을 획득하고, 그 뒤 row
  `SELECT ... FOR UPDATE`와 write를 수행한다. 따라서 두 row가 없는 최초 generic core/access 경쟁도
  직렬화되며 stale CAS는 rollback한다.
- generic core PUT은 authority 생성 후 네 protected projection 필드를 보존한다. access projection은
  기존 core를 clone한 뒤 그 네 필드만 갱신하므로 기존 CR state/round/revision/approval/transition을
  변경하지 않는다. CR state-machine 파일이나 transition 계약은 변경하지 않았다.
- 제품 diff에 deployment-specific host, port, credential, topic, timezone, 기본 subject/user/System/
  platform literal을 추가하지 않았다. 신규 dependency, table, service, IAM/OIDC/Keycloak도 없다.

## 4. 독립 실행 결과

비-PTY에서 PATH를 `/Users/everreal/.nvm/versions/node/v25.6.1/bin`으로 고정했다. 최초
`node_modules`가 없어 exact lockfile로 `npm ci`를 실행했고 368 packages 설치, audit 취약점 0건,
tracked package/lockfile 변경 0건을 확인했다.

| 순서 | 명령 | 결과 |
|---:|---|---|
| 1 | `npm ci` | PASS, 368 packages, vulnerabilities 0 |
| 2 | `node --test poc-state-store.test.mjs` | PASS, 11/11 |
| 3 | `npm run build:poc` | PASS, 기존 500 kB 초과 chunk warning만 존재 |
| 4 | `node --test poc-server.test.mjs` | PASS, 12/12 |
| 5 | `npm run lint` | PASS, error/warning 0 |
| 6 | `npm run build:poc` | PASS, 동일 비차단 chunk warning |
| 7 | `npm run test:poc-server` | PASS, 31/31 |
| 8 | `git diff --check 1818bac1...HEAD` | PASS |
| 9 | `git diff --check 97b88b99...HEAD` | PASS |

## 5. 판정과 미실행 범위

이 exact candidate의 T06A는 local source 독립 검증을 통과했다. 이전 lint 실패는 validator 약화 없이
해소되었고 권위, CAS, advisory lock, generic core fence, no-hardcoding 및 CR zero-effect 계약에서 새
차단 finding은 확인되지 않았다.

- DEV 플랫폼 runtime 통합: `NOT_EXECUTED`
- 실제 PostgreSQL 동시 부하/실서비스 subject provisioning: `NOT_EXECUTED`
- PREP: `NOT_EXECUTED`
- OPS: `NOT_EXECUTED`
- TARGET: `NOT_EXECUTED`
- push/merge/publication: `NOT_EXECUTED`
- T09 fresh assurance audit: `PENDING`

따라서 이 결과는 `RUNTIME_VERIFIED`, release-ready 또는 G1-G4 승인을 의미하지 않는다.
