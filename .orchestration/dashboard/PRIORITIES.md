# 현재 우선순위 대시보드 — Change Management 제품화 마감

기준 product는 `4aea6d19c64253130e00d997c2837b74fac4837d`, 기준 evidence는
`313a559bdd9300d3ee2021935d2dbac0319bafd1`이다. 구현, fresh validation과 실제 DEV runtime을
구분하며 PREP/OPS 결과를 추정하지 않는다.

| Task | 담당 기능 | 사용자 기능 | 구현 상태 | DEV Runtime | PREP Runtime | Next |
|---|---|---|---|---|---|---|
| T00–T02 | discovery·capture architecture | 보장 범위와 current/history 분리 | IMPLEMENTED / VALIDATION_PASS | architecture contract verified against DEV evidence | TARGET_RECHECK_REQUIRED | target provider/retention 재확인 |
| T03N | Node ledger/source/checkpoint/link persistence | 재시작 후 변경 이력 보존 | IMPLEMENTED / VALIDATION_PASS | RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | 기존 volume SQL apply 검증 |
| T03-PYTHON | Python/Alembic prototype | 현재 POC 사용자 기능 없음 | DEFERRED / NOT_RUNTIME_INTEGRATED | NOT_RUNTIME_INTEGRATED | NOT_INCLUDED_IN_POC_CLAIM | release disposition 유지 |
| T04 | MCL decode·normalize·dedup·checkpoint | 중간 변경 사건 | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | Kafka/SR/env/exact boundary recheck |
| Scheduler | KST 00:00·catch-up·singleton receipt | 자동 capture/reconcile | IMPLEMENTED / VALIDATION_PASS | startup/catch-up RUNTIME_VERIFIED; DAILY_CLOCK_NOT_OBSERVED | TARGET_RECHECK_REQUIRED | actual midnight 관찰 backlog |
| T05 | current projection/cache/성능/lifecycle | Search/Tree/Detail 최신성 | IMPLEMENTED / VALIDATION_PASS | Search/Tree/lifecycle RUNTIME_VERIFIED; vector provider debt | TARGET_RECHECK_REQUIRED | vector/current target recheck |
| T06 | user/role/System 권위·CR API | 권한별 CR link/weekly | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target server-held subject 재확인 |
| T07 | Monitoring·weekly·link/reverse UI | 데이터 변경현황·CR STATUS OVERVIEW | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target browser smoke |
| T08 | 기존 제품 전체 통합 E2E | 전체 회귀 | HOLD | Change Management focused/full evidence만 current | NOT_EXECUTED | 별도 승인 후 수행 |
| T09 | fresh assurance audit | 최종 보증 | HOLD | NOT_EXECUTED | NOT_EXECUTED | T08 이후 별도 승인 |
| Search / Catalog / Tree / Detail | current metadata 조회 | 카탈로그 탐색 | IMPLEMENTED / VALIDATION_PASS | RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | provider latency/Detail target smoke |
| Current metadata sync | DataHub current → PG/Redis/vector | 최신 자산·삭제·재활성화 | IMPLEMENTED / VALIDATION_PASS | PG/Redis lifecycle RUNTIME_VERIFIED; vector debt | TARGET_RECHECK_REQUIRED | vector provider 복구 후 재검증 |
| Schema / Metadata Change History | schema/metadata/lifecycle ledger | 변경 이력 | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target MCL 1건 |
| MCL capture / checkpoint | bounded Kafka → ledger → checkpoint | 중간 변경 보존 | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target topic/retention/schema |
| User / Role 관리 | CRUD·active·4 roles | 사용자 관리 | IMPLEMENTED / VALIDATION_PASS | RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target access bootstrap |
| System / 담당자 관리 | schema scope·assignment·responsibility·priority | 시스템/담당자 | IMPLEMENTED / VALIDATION_PASS | RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target assignment smoke |
| CR link/unlink / reverse history | primary/candidate/SET·CLEAR history | CR 추적 | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target compatible CR smoke |
| Weekly / CR STATUS OVERVIEW | schema/System/owner/stage 집계 | 변경관리 상단 요약 | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target KST boundary smoke |
| Monitoring 데이터 변경현황 | native summary/filter/detail | 변경현황 기본 탭 | IMPLEMENTED / VALIDATION_PASS | COMPLETE_RUNTIME_VERIFIED | TARGET_RECHECK_REQUIRED | target populated-event smoke |
| 기존 Grafana tabs | external dashboard 유지 | 외부 모니터링 | IMPLEMENTED | config regression covered; DEV NOT_CONFIGURED | TARGET_RECHECK_REQUIRED | target CSP/embed 검증 |
| Registration Manual/BULK | 기존 등록 workflow | 등록관리 | DEFERRED (이번 closeout 밖) | historical evidence only | TARGET_RECHECK_REQUIRED | T08 backlog |
| Chat GENERAL/VECTOR/GRAPH | 기존 Chat/current correctness | Chat | PARTIAL / VECTOR_PROVIDER_UNAVAILABLE | Search/Tree current PASS; vector unavailable | TARGET_RECHECK_REQUIRED | CHAT-REFINEMENT backlog |
| Quality / GX | 기존 Quality 및 GX 연계 | 품질관리 | DEFERRED | 이번 closeout 미실행 | TARGET_RECHECK_REQUIRED | QUALITY-GX-INTEGRATION |
| Governance / Glossary / Knowledge | 기존 기능 | 거버넌스·용어·Knowledge | DEFERRED (이번 closeout 밖) | historical evidence only | TARGET_RECHECK_REQUIRED | T08 backlog |
| Deployment productization | config·runbook·architecture·screen/process spec | 재현 가능한 운영 | IN_PROGRESS (docs-only) | source consistency validation pending | TARGET_RECHECK_REQUIRED | docs validation + local commit |
| Release / PREP / OPS | publication·target validation | 배포 | HOLD | origin/dev=`737cee10` | PREP recheck / OPS NOT_EXECUTED | G1/G2 승인 전 push 금지 |

## Backlog

- `VECTOR_PROVIDER_UNAVAILABLE`, Chat/vector deleted-current target recheck
- PREP targeted recheck와 OPS validation/deployment
- `DAILY_CLOCK_NOT_OBSERVED`
- GX/Quality integration, Chat refinement, Vite chunk-size warning
- secret-file injection, `Dockerfile.local` drift
- `MODULAR_PRODUCT_ARCHITECTURE` — ADR-0124에 따라 실제 요구와 contract tests 이후 단계화

## Gates

G1 `NOT_APPROVED` · G2 `NOT_APPROVED` · G3 `NOT_APPROVED` · G4 `NOT_APPROVED`
