# DataRiver 현재 제품 우선순위

기준 Product SHA와 배포 OCI revision은
`43e74a0f4a6f696a64aa70ff8afeb681bf14c2d8`로 일치한다. authoritative runtime은 Node POC이며
DEV Web은 `http://127.0.0.1:39083`에서 healthy다. 아래 상태는 현재 source/runtime 근거이며
PREP/OPS 또는 publication 결과를 추정하지 않는다.

## 1. 계정 및 접근권한

- 현재 상태: `COMPLETE_RUNTIME_VERIFIED` — 핵심 구조 완료.
- 완료: 로그인/서버 세션, User/Role, 정확한 Table grant, 보안등급, 고정 기능정책, System 담당,
  CR 3-lane, Catalog/검색/Vector/AUTO 권한 필터.
- 남은 작업: 각 새 제품기능에서 기존 helper를 연결하고 negative/regression test만 추가.
- 다음 작업: Account/Auth 자체를 더 확장하지 않는다.
- 진행을 막는 문제: 없음. Graph/GX 등은 해당 기능의 별도 gap이다.

## 2. 변경관리 / MCL 자동감지

- 현재 상태: `COMPLETE_RUNTIME_VERIFIED` — current source 자동감지 기준선 유지.
- 완료: source/checkpoint/exact ledger, catch-up, replay idempotency, schema/metadata/lifecycle capture,
  scheduler startup/catch-up, Monitoring current-source 상태. 현재 source/checkpoint/ledger/CR-link는
  2/2/66/4다.
- 남은 작업: `ACTUAL_KST_MIDNIGHT`, `MCL_DEV_BINDING_REPRODUCIBILITY`.
- 다음 작업: core mutation 없이 실제 KST 00:00 target acceptance만 별도 관찰.
- 진행을 막는 문제: 실제 자정 wall-clock 미관찰(`TARGET_RECHECK_REQUIRED`).

## 3. 개발용 지원서비스

| 서비스 | 현재 상태 | 완료 | 남은 작업 / blocker |
|---|---|---|---|
| Airflow | `COMPLETE_RUNTIME_VERIFIED` | 3.3.0, exact Registration DAG, loopback, Web binding, actual callback→READY | PREP/OPS 별도 |
| MinIO | `COMPLETE_RUNTIME_VERIFIED` | 기존 external DEV endpoint, loopback, 5 buckets, Product upload/complete와 object cleanup | 외부 DEV ownership 명시 유지 |
| GX | `IMPLEMENTED_NOT_VERIFIED` / `PARTIAL` | exact 1.19.1 worker/compiler 실행 seam | `GX_CANONICAL_RUNTIME_CONTRACT_REQUIRED`: result→DataHub Assertion/GMS receipt 계약 부재 |

새 service/container/provider/version은 추가하지 않았다. GX 준비와 Quality Product 정의는 서로
다른 상태로 관리한다.

## 4. 등록관리

- 현재 상태: auth/preparation/manual apply/candidate-to-CR/apply-report slice `COMPLETE_RUNTIME_VERIFIED`;
  전체 `PARTIAL`.
- 완료: data_steward/admin mutation role gate, Manager read-only history, current TABLE + grant + grade + fixed Registration
  policy + Responsible System AND, owner isolation, 404 hiding, count/receipt authorization 후 계산,
  request-time grant/mapping 철회, MinIO→preparation→Airflow callback→READY→candidate 실제 E2E,
  sparse empty manual metadata와 실제 description apply receipt, READY candidate→서버 작성 CR
  exactly-once, ETag/idempotency/CAS, provider write 0, 서버 권한의 정확한 `NOT_STARTED`
  apply-report와 private/no-store.
- 단계별 상태:
  - 업로드/준비: 완료(재시작 복구는 HOLD)
  - Airflow 처리: 완료
  - 후보/미리보기: 완료
  - 변경요청 생성: 완료
  - 변경요청 승인: 기존 3-lane 기준선 완료
  - 실제 적용: 시작 안 됨 / 일부
  - 적용 결과: 서버의 truthful `NOT_STARTED` 조회 완료
  - 재시작 복구: `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION`
- 남은 작업: durable preparation/outbox/provider-apply와 typed 전체 surface/target acceptance.
- 왜 필요한가: 담당자가 허용된 현재 Table만 안전하게 준비·등록하도록 보장한다.
- 다음 작업: durable receipt/candidate/outbox/apply ownership과 최소 schema를 사용자 결정 후
  기존 CR apply 계약에 연결한다.
- 진행을 막는 문제: `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION`; Registration 전체는 durable
  preparation/outbox/provider-apply와 target gate 때문에 `PARTIAL`.

## 5. 거버넌스 — 정책·표준 문서 등록 및 관리

- 현재 상태: `COMPLETE_RUNTIME_VERIFIED`.
- 완료: 모든 active user read와 data_steward/manager/admin create, DRAFT update, archive; viewer/developer mutation 403.
- 남은 작업: 추가 검색·workflow는 명시적 사용자 요구가 있을 때만 별도 정의.
- 왜 필요한가: 조직의 최신 정책·표준을 등록하고 조회하기 위해 필요하다.
- 다음 작업: 현재 완료 기준선을 유지한다.
- 진행을 막는 문제: 없음. 문서를 Table에 억지로 연결하거나 generic resource ACL을 만들지 않는다.

## 6. Chat / 검색

- 현재 상태: General/Vector/AUTO와 pre-K7 DataHub-lineage Graph `COMPLETE_RUNTIME_VERIFIED`;
  actual fallback 실행과 K7 Knowledge routing은 `PARTIAL`.
- 완료: provider/embedding/reranker, authorized URN pre-ranking, authorized route/context/citation,
  empty scope `NO_LIVE_EVIDENCE`, General Chat의 metadata 비강제.
- 남은 작업: actual unresolved-lineage fallback, K7 authorized Knowledge Asset routing,
  provider traversal/total leakage와 bounded latency/refinement.
- 다음 작업: 현재 verified path를 유지하고 K2~K6 이후 K7 bounded usage profile에서만 Knowledge를 연결.
- 진행을 막는 문제: Knowledge route는 K7 dependency이며 현재 pre-K7 Chat을 막지 않는다.

## 7. 지식관리

- 현재 상태: `PARTIAL`; K0~K5 `COMPLETE_RUNTIME_VERIFIED`, K6 `NOT_STARTED`.
- 완료: exact Table/Column URN identity/provenance, Registry/version, typed T-Box, Catalog Source
  Proposal, 두 additive table의 durable A-Box preview/confirm/DRAFT changeset/projection/replay,
  request-time authorization, restart recovery와 disposable cleanup.
- K5 결과: bounded Relation fixture에서 Preview Node 2 / Relation 1, confirm/replay Node 2 /
  distinct Edge 1, duplicate 0, exact endpoint/version provenance, no-grant `403`, exact cleanup,
  Product/OCI 일치.
- 남은 작업: K6 Knowledge Chat, K7 Main Chat, K8 MCP, K9 Default Assets.
- 다음 작업: 이번 closeout에서는 K6를 시작하지 않는다. 별도 승인/리소스에서 bounded Node
  graph/release/snapshot/graphrag routes를 구현·검증한다.
- 진행을 막는 문제: K5 없음. Knowledge 전체는 K6~K9 때문에 `PARTIAL`.

## 8. 품질관리 — 사용자 추가 기능 정의 대기 / GX 준비

- 현재 상태: Quality Product `USER_FEATURE_DEFINITION_REQUIRED`; GX `PARTIAL`.
- 완료: 기존 Quality UI/control-plane 구상, exact GX version과 worker/compiler seam.
- 남은 작업: 사용자 제품기능 정의, result→DataHub Assertion emission, GMS/UI assertion E2E.
- 다음 작업: fake result 없이 canonical PRD를 유지하고 정의 후 작은 slice로 진행.
- 진행을 막는 문제: Quality 정의와 Assertion egress 부재.

## 9. Admin

- 현재 상태: `COMPLETE_RUNTIME_VERIFIED`.
- 완료: User/Role/active/grade/grant, Responsible System/priority, credential/session, System master,
  Table↔System, 고정 feature policy.
- 남은 작업: 실제 제품기능에 필요한 최소 설정만 추가.
- 다음 작업: custom role, generic permission console, workspace/tenant/workflow builder 금지.
- 진행을 막는 문제: 없음. inspection Admin은 validation dummy가 아니다.

## 10. 배포·운영·기술 Backlog

- 완료: deterministic Web/provider restart, canonical port, exact Product/OCI, loopback binding.
- 남은 작업: actual KST midnight, MCL DEV binding reproducibility, embedding-generation GC,
  migration contract, Dockerfile drift, Vite chunk, browserless fallback, Timeline backfill,
  modular architecture, PREP/OPS acceptance.
- Gate: G1/G2/G3/G4 모두 미승인. push/PREP/OPS mutation 없음.

## 승인 필요

| Approval ID | 요청 | 위험 | 승인 전 가능한 작업 |
|---|---|---|---|
| `HOLD_REGISTRATION_DURABLE_STORAGE_DECISION` | preparation receipt/candidate/outbox/apply의 최소 durable schema·retention·소유권 결정 | 근거 없이 table/queue/worker를 만들면 두 번째 workflow가 됨 | GX/Governance/Chat read-only, 기존 Registration 회귀검증 |
| `GX_CANONICAL_RUNTIME_CONTRACT_REQUIRED` | 최근 PREP/OPS의 exact result→DataHub Assertion egress 계약 또는 사용자 기능범위 제공 | 임의 egress는 Quality architecture와 provider identity를 새로 만들 위험 | Registration 후속 계약 audit, Governance/Chat read-only |
| `HOLD_G1_G2_NOT_APPROVED` | merge/push/DEV publication | 원격 계보 변경 | 로컬 DEV 검증과 문서화 |
| `HOLD_PREP_G3` | PREP mutation/acceptance | 준비 환경 상태 변경 | DEV/read-only discovery |
| `HOLD_OPS_G4` | OPS mutation/acceptance | 운영 영향 | DEV/read-only discovery |

## 기술 상태 요약

```text
Product / deployed OCI 43e74a0f4a6f696a64aa70ff8afeb681bf14c2d8
K5-R focused tests    server 2 / 2; frontend 23 / 23 PASS
Prior K5 full tests   Node 109 / 109; frontend 87 files, 617 / 617 PASS
K5 tables/migrations  2 / 1
new dependencies/services/containers/queues/workers/frameworks/capabilities = 0
```
