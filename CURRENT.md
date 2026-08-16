# CURRENT.md — PHASE 1A LOCAL ACCOUNT / SERVER SESSION

## 기준선

- Product SHA: `618b9713059ba7e31b807ceae3b401766a313668`
- published origin/dev: `ef41447a1d470119c1a83280e261d4be411354ef`
- lineage: origin/dev 위의 4개 fast-forward product commit; push/publication 미실행
- evidence: `.orchestration/evidence/DEV-LOCAL-AUTH-PHASE1A-RUNTIME.md`와 matching receipt
- environment: `DEV_MAC_ARM64`, Node `22.19.0`, image OCI revision이 Product SHA와 일치

## Canonical status

- PHASE 1A-0 replacement feasibility/access CAS gate: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1A-1 loopback/private-network containment: `COMPLETE_RUNTIME_VERIFIED`
- 다른 host에서의 remote negative network probe: `TARGET_RECHECK_REQUIRED`
- PHASE 1A-2 local credential/opaque server session/request principal: `COMPLETE_RUNTIME_VERIFIED`
- PHASE 1A-3 operator bootstrap/direct login shell: `COMPLETE_RUNTIME_VERIFIED`
- Account/Auth 전체: `PARTIAL`
  - PHASE 1B capability/System route coverage, 1C full Admin user management, 1D sensitivity,
    1E legacy active-path retirement, 1F full multi-account acceptance는 아직 완료하지 않음

## 현재 권위와 안전 경계

- 기존 `change-history-access-v1` 문서가 role/System/application access의 유일한 권위다.
- `poc_local_credentials`와 `poc_local_sessions`는 인증 자료만 저장한다. session은 token 원문이
  아니라 SHA-256 hash를 저장하며 role/System snapshot을 저장하지 않는다.
- 모든 보호 API는 request-scoped session subject를 최신 access document에 다시 결합한다.
- 기존 4개 synthetic fixture는 그대로 유지했고 credential을 만들지 않았다. 신규 human DEV
  fixture 2개만 공식 access CAS + operator bootstrap 경로로 만들었으며 모든 검증 session은 revoke했다.
- FastAPI/Keycloak/OIDC/Workspace는 현재 Node POC authentication startup dependency가 아니다.
  reusable/historical source는 삭제하지 않았고 physical retirement는 PHASE 1E 이후다.

## Frozen baseline과 현재 deployment readiness

- Change History/MCL, CR, Monitoring, Search/Tree와 Scheduler의 과거 검증 capability는 보존됐다.
- 현재 배포는 Scheduler `false`, 필수 MCL binding `0/9`이므로 지금 즉시 capture/catch-up 가능한
  배포 상태는 아니다. 이 config 상태를 기존 runtime capability 검증과 혼동하지 않는다.
- read-only 재확인: ledger `46`, source `2`, checkpoint `2`, CR link event `4`, scheduler receipt `2` 보존.

## Gates

- G1 SOURCE_MERGE: `NOT_APPROVED`
- G2 DEV_PUBLISH: `NOT_APPROVED`
- G3 PREP mutation: `NOT_APPROVED`
- G4 OPS mutation: `NOT_APPROVED`
