# 현재 우선순위 대시보드 — PHASE 1A Local Account / Server Session

기준 Product SHA는 `618b9713059ba7e31b807ceae3b401766a313668`, published origin/dev는
`ef41447a1d470119c1a83280e261d4be411354ef`이다. 구현, fresh validation과 실제 DEV runtime을
구분하며 PREP/OPS 결과를 추정하지 않는다. Account/Auth 상태는 canonical vocabulary만 사용한다.

| Task | 담당 기능 | 사용자 기능 | 구현 상태 | DEV Runtime | PREP Runtime | Next |
|---|---|---|---|---|---|---|
| PHASE 1A | local credential·opaque session·request principal·operator bootstrap | local login/logout | `COMPLETE_RUNTIME_VERIFIED` | 401/403/Origin/spoof/concurrency/restart/browser shell verified | `TARGET_RECHECK_REQUIRED` | G1/G2 전 publication 금지 |
| PHASE 1A-1 | loopback/private-network containment | DEV local browser access | `COMPLETE_RUNTIME_VERIFIED` | Web/Airflow/owned support ports loopback | `TARGET_RECHECK_REQUIRED` | remote-host negative probe |
| PHASE 1B | central capability/System route coverage | feature별 일관된 권한 | `BACKLOG` | 미실행 | `TARGET_RECHECK_REQUIRED` | route inventory에 capability fence 연결 |
| PHASE 1C | full Admin account management | user/role/System/reset/revoke | `PARTIAL` | operator bootstrap만 verified | `TARGET_RECHECK_REQUIRED` | 최소 Admin API/UI slice |
| PHASE 1D | normal/restricted/credential sensitivity | 조회·retrieval 데이터 경계 | `BACKLOG` | 미실행 | `TARGET_RECHECK_REQUIRED` | policy 확정 후 동일 backend fence 적용 |
| PHASE 1E | legacy auth active-path retirement | local auth 단일 runtime | `BACKLOG` | reusable/historical source 보존 | `TARGET_RECHECK_REQUIRED` | replacement acceptance 뒤 작은 retirement |
| PHASE 1F | full account isolation/security acceptance | 두 사용자 동시 전체 기능 | `BACKLOG` | 1A request isolation만 verified | `TARGET_RECHECK_REQUIRED` | 1B~1E 이후 전체 matrix |
| T00–T02 | discovery·capture architecture | 보장 범위와 current/history 분리 | `COMPLETE_RUNTIME_VERIFIED` | architecture contract verified against DEV evidence | `TARGET_RECHECK_REQUIRED` | target provider/retention 재확인 |
| T03N | Node ledger/source/checkpoint/link persistence | 재시작 후 변경 이력 보존 | `COMPLETE_RUNTIME_VERIFIED` | DEV durable restart verified | `TARGET_RECHECK_REQUIRED` | 기존 volume SQL apply 검증 |
| T03-PYTHON | Python/Alembic prototype | 현재 POC 사용자 기능 없음 | `PARTIAL` | Node POC runtime에 미통합 | `TARGET_RECHECK_REQUIRED` | release disposition 유지 |
| T04 | MCL decode·normalize·dedup·checkpoint | 중간 변경 사건 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | Kafka/SR/env/exact boundary recheck |
| Scheduler | KST 00:00·catch-up·singleton receipt | 자동 capture/reconcile | `COMPLETE_RUNTIME_VERIFIED` | startup/catch-up verified; `DAILY_CLOCK_NOT_OBSERVED` | `TARGET_RECHECK_REQUIRED` | actual midnight 관찰 backlog |
| T05 | current projection/cache/성능/lifecycle | Search/Tree/Detail 최신성 | `COMPLETE_RUNTIME_VERIFIED` | Search/Tree/lifecycle verified; vector provider debt | `TARGET_RECHECK_REQUIRED` | vector/current target recheck |
| T06 | user/role/System 권위·CR API | 권한별 CR link/weekly | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target server-held subject 재확인 |
| T07 | Monitoring·weekly·link/reverse UI | 데이터 변경현황·CR STATUS OVERVIEW | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target browser smoke |
| T08 | 기존 제품 전체 통합 E2E | 전체 회귀 | `BACKLOG` | 현재 Auth slice 범위 밖 | `TARGET_RECHECK_REQUIRED` | 별도 승인 후 수행 |
| T09 | fresh assurance audit | 최종 보증 | `BACKLOG` | 현재 Auth slice 범위 밖 | `TARGET_RECHECK_REQUIRED` | T08 이후 별도 승인 |
| Search / Catalog / Tree / Detail | current metadata 조회 | 카탈로그 탐색 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | provider latency/Detail target smoke |
| Current metadata sync | DataHub current → PG/Redis/vector | 최신 자산·삭제·재활성화 | `PARTIAL` | PG/Redis lifecycle verified; vector debt | `TARGET_RECHECK_REQUIRED` | vector provider 복구 후 재검증 |
| Schema / Metadata Change History | schema/metadata/lifecycle ledger | 변경 이력 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target MCL 1건 |
| MCL capture / checkpoint | bounded Kafka → ledger → checkpoint | 중간 변경 보존 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target topic/retention/schema |
| Existing User / Role access | CRUD·active·4 roles | access-document 사용자 관리 | `COMPLETE_RUNTIME_VERIFIED` | DEV access semantics verified | `TARGET_RECHECK_REQUIRED` | PHASE 1C credential 관리와 구분 |
| System / 담당자 관리 | schema scope·assignment·responsibility·priority | 시스템/담당자 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target assignment smoke |
| CR link/unlink / reverse history | primary/candidate/SET·CLEAR history | CR 추적 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target compatible CR smoke |
| Weekly / CR STATUS OVERVIEW | schema/System/owner/stage 집계 | 변경관리 상단 요약 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target KST boundary smoke |
| Monitoring 데이터 변경현황 | native summary/filter/detail | 변경현황 기본 탭 | `COMPLETE_RUNTIME_VERIFIED` | DEV runtime verified | `TARGET_RECHECK_REQUIRED` | target populated-event smoke |
| 기존 Grafana tabs | external dashboard 유지 | 외부 모니터링 | `PARTIAL` | config regression covered; DEV not configured | `TARGET_RECHECK_REQUIRED` | target CSP/embed 검증 |
| Registration Manual/BULK | 기존 등록 workflow | 등록관리 | `PARTIAL` | historical evidence only | `TARGET_RECHECK_REQUIRED` | T08 backlog |
| Chat GENERAL/VECTOR/GRAPH | 기존 Chat/current correctness | Chat | `PARTIAL` | Search/Tree current verified; `VECTOR_PROVIDER_UNAVAILABLE` | `TARGET_RECHECK_REQUIRED` | CHAT-REFINEMENT backlog |
| Quality / GX | 기존 Quality 및 GX 연계 | 품질관리 | `PARTIAL` | 현재 Node POC/GX actual E2E 미완료 | `TARGET_RECHECK_REQUIRED` | QUALITY-GX-INTEGRATION |
| Governance / Glossary / Knowledge | 기존 기능 | 거버넌스·용어·Knowledge | `PARTIAL` | historical evidence only | `TARGET_RECHECK_REQUIRED` | T08 backlog |
| Deployment productization | config·runbook·architecture·screen/process spec | 재현 가능한 운영 | `COMPLETE_RUNTIME_VERIFIED` | current Auth Compose/config/docs static gate verified | `TARGET_RECHECK_REQUIRED` | target deployment acceptance |
| Release / PREP / OPS | publication·target validation | 배포 | `IMPLEMENTED_NOT_VERIFIED` | unpublished Product SHA; origin/dev=`ef41447a` | `TARGET_RECHECK_REQUIRED` | G1/G2 승인 전 push 금지 |

## Backlog

- `VECTOR_PROVIDER_UNAVAILABLE`, Chat/vector deleted-current target recheck
- PREP targeted recheck와 OPS validation/deployment
- `DAILY_CLOCK_NOT_OBSERVED`
- GX/Quality integration, Chat refinement, Vite chunk-size warning
- secret-file injection, `Dockerfile.local` drift
- `MODULAR_PRODUCT_ARCHITECTURE` — ADR-0124에 따라 실제 요구와 contract tests 이후 단계화

## Gates

G1 `NOT_APPROVED` · G2 `NOT_APPROVED` · G3 `NOT_APPROVED` · G4 `NOT_APPROVED`
