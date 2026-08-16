# CURRENT.md — PHASE 1B CENTRAL AUTHORIZATION

## 기준선과 lineage

- Repository HEAD의 product boundary: `e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa`
- PHASE 1A frozen Product SHA: `618b9713059ba7e31b807ceae3b401766a313668`
- PHASE 1A Evidence SHA: `8c1f93a456d0fe51e46987b72d66f563f6467d73`
- published `origin/dev`: `ef41447a1d470119c1a83280e261d4be411354ef`
- PHASE 1B evidence: `.orchestration/evidence/DEV-PHASE1B-CENTRAL-AUTHORIZATION-RUNTIME.md`
  및 matching receipt. Evidence SHA는 이 evidence-only handoff commit이다.
- publication: G1/G2 미승인으로 push하지 않았다. PREP/OPS mutation도 수행하지 않았다.

## Canonical status

- PHASE 1A local account/server session: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1B central capability/System authorization: `COMPLETE_RUNTIME_VERIFIED`
- 다른 host에서의 remote negative network probe: `TARGET_RECHECK_REQUIRED`
- 현재 Scheduler/MCL deployment readiness: `TARGET_RECHECK_REQUIRED`
- Account/Auth 전체: `PARTIAL`
  - PHASE 1C Admin User Management, PHASE 1D sensitivity, PHASE 1E legacy retirement,
    PHASE 1F final multi-account/data-isolation acceptance가 남아 있다.

## 현재 authority와 authorization contract

- local credential + opaque server session은 request별 `subject_id`만 인증한다.
- `change-history-access-v1` 문서가 active/role/System/application access의 유일한 권위다.
- 매 요청이 최신 access document로 principal을 재구성한다. credential/session/browser/client
  claim은 role 또는 System 권위가 아니다.
- 중앙 module 하나가 5개 role과 정확히 15개 capability를 정의한다.
  - `viewer`: 6
  - `developer`: 9
  - `data_steward`: 12
  - `manager`: 14
  - `admin`: 15
- manager는 ADR-0107의 승인된 engineering/steward 상속 + Knowledge/Governance manage/review
  의미를 따른다.
- System-bound mutation은 current assignment와 실제 target System을 함께 검사하고,
  ambiguous/unresolved target은 fail closed한다. PHASE 1D sensitivity는 아직 적용하지 않았다.

## Route / feature boundary

- backend route registry: 49개 모두 분류됨.
  - `ANONYMOUS=7`
  - `AUTHENTICATED=2`
  - `CAPABILITY_PROTECTED=38`
  - `INTERNAL_SERVICE=1`
  - `DISABLED=1`
  - `UNKNOWN=0`
- Catalog, Search, Tree, Detail, Chat, Change History/CR, Monitoring, Knowledge/Governance,
  Quality read seam, access admin 및 raw provider gateway가 같은 request principal을 사용한다.
- dynamic core-state write는 top-level key diff + ETag/CAS + capability/System policy를 적용한다.
- Airflow bulk-preparation callback만 exact service-token route이며 일반 API impersonation은 불가하다.
- frontend menu/direct-page UX는 `/auth/me`의 server capability를 사용하지만 security boundary는
  backend다.

## DEV runtime과 계정 정리

- Web: healthy, `127.0.0.1:39083`, Node `22.19.0`, `linux/amd64` image.
- OCI revision: `e13dbb4f8412937e1d60bd45f83e0e91dc3e91aa`.
- Airflow와 owned supporting-service host ports는 loopback/private-network containment를 유지한다.
- 검증에는 admin/viewer/developer/data_steward/manager를 사용했다.
- 검증 후 공식 version-guarded CLI로 PHASE 1A/1B validation credential 7개를 모두 disable하고
  모든 session을 revoke했다. 최종 enabled credential `0`, active session `0`이다.
- access user 11개와 history reference는 보존했으며 synthetic `checkpoint-*`에는 credential을
  만들지 않았다.

## Frozen baseline / readiness

- 최종 read-only 검증: source `2`, ledger `46`(identity/position duplicate `0`), CR link `4`,
  checkpoint `2`, Scheduler receipt `2`, append-only trigger `2`.
- checkpoint tuples: `51815/52854/v1040`, `52849/52942/v94`.
- MCL mutation/reset, CR semantic change, PREP/OPS mutation은 없었다.
- 현재 Scheduler는 disabled이고 필수 MCL binding은 `0/9`다. 과거 runtime capability와 현재
  deployment readiness를 혼동하지 않는다.
- Quality/GX execution은 runtime available하지 않고, Chat General은 authorization을 통과한 뒤
  기존 external provider fetch failure를 반환했다.

## Fresh validation

- final Product SHA에서 `test:poc-server` 60/60, frontend 586/586, focused authorization 5/5,
  typecheck, lint, `build:poc`, base/Airflow Compose render, secret/hardcoding scan,
  `git diff --check`가 통과했다.
- 기존 Vite 500 kB chunk warning과 browserless loopback fallback은 backlog다.
- temporary password/cookie 자료는 evidence 정리 후 삭제했다. secret 원문은 evidence나 Git에 없다.

## Gates / next slice

- G1 SOURCE_MERGE: `NOT_APPROVED`
- G2 DEV_PUBLISH: `NOT_APPROVED`
- G3 PREP mutation: `NOT_APPROVED`
- G4 OPS mutation: `NOT_APPROVED`
- next smallest slice: PHASE 1C minimal Admin User Management only.
