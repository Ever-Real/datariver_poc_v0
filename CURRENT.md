# CURRENT.md — CHANGE MANAGEMENT PRODUCTIZATION CLOSEOUT

## 기준선

- product SHA: `4aea6d19c64253130e00d997c2837b74fac4837d`
- evidence SHA: `313a559bdd9300d3ee2021935d2dbac0319bafd1`
- origin/dev: `737cee10daaf3af1680e11cdb43b2779d0865756`
- evidence relation: product → evidence descendant, 제품 파일 추가 변경 없음
- environment evidence: `DEV_MAC_ARM64`, Node `22.19.0`, actual provider/runtime E2E
- unpublished MCL docs hold: `e7ba19b67e02153df34d1066c9d972420983db09`; product lineage 밖, 유효 내용은 현재 closeout 문서에 갱신 통합

## 현재 기능 상태

- Change History/MCL core: `COMPLETE_RUNTIME_VERIFIED` (DEV)
- Scheduler startup catch-up/same-day singleton receipt: `COMPLETE_RUNTIME_VERIFIED` (DEV)
- actual KST midnight: `DAILY_CLOCK_NOT_OBSERVED`
- User/Role/System access authority: `COMPLETE_RUNTIME_VERIFIED` (DEV)
- actual CR primary link/unlink/reverse history/weekly/STATUS OVERVIEW: `COMPLETE_RUNTIME_VERIFIED` (DEV)
- Monitoring actual-event path: `COMPLETE_RUNTIME_VERIFIED` (DEV)
- Search/Tree/current lifecycle: `COMPLETE_RUNTIME_VERIFIED` (DEV)
- Vector provider: `VECTOR_PROVIDER_UNAVAILABLE`, target recheck debt
- PREP: `TARGET_RECHECK_REQUIRED`
- OPS: `NOT_EXECUTED`

## 제품화 closeout

- 신규 기능·CR/MCL domain semantics 변경 없음
- 기존 문서 체계를 재사용해 제품화 기준서, MCL runbook, configuration reference와 modularization ADR을 정리
- `.env.example`은 실제 source/Compose env contract와 동기화하고 실제 IP/hash/credential을 포함하지 않음
- validation 후 local docs/evidence SHA만 생성하며 push하지 않음

## Gates

- closeout G1 SOURCE_MERGE: `NOT_APPROVED`
- closeout G2 DEV_PUBLISH: `NOT_APPROVED`
- G3 PREP mutation: `NOT_APPROVED`
- G4 OPS mutation: `NOT_APPROVED`
