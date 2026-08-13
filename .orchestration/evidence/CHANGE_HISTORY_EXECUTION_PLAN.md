## CHANGE_HISTORY_EXECUTION_PLAN

### BASELINE
* exact_sha: 78e533db6db0352dc0b6d44a557db22a7b05162c (T00/T01 discovery exact base)
* branch: dev / task branches
* dirty_state: discovery worktrees clean; dev had only same-owner harness ledger dirt before plan; after 8bc8001 clean
* environment: DEV_MAC_ARM64

### EXACT_CAPTURE
* timeline_internal_status: ENDPOINT_ADVERTISED_DATA_UNVERIFIED
* categories: five categories UNKNOWN
* retained_history: UNKNOWN
* retention_loss_risk: UNKNOWN
* mcl_status: INFRA_OBSERVED_TOPIC_SCHEMA_OFFSET_NOT_EXECUTED
* selected_candidate: UNDECIDED_PENDING_TARGET_PROBE
* selection_gap: exact PREP/admin evidence list

### CURRENT_DATA_PATH
* table_load_path: UI -> POC API -> GMS GraphQL; unfiltered direct scroll; filtered full inventory
* DataHub_calls: code patterns page 250 cap 10002; per-request runtime metrics absent
* Redis: actual established, 15m inventory/60s asset acceleration; optional
* PostgreSQL: actual established, poc_state/current + poc_catalog_embedding
* pgvector: READY 2000 latest generation
* current_projection: PostgreSQL state/vector, DataHub current only
* cache_invalidation: TTL and changed embedding behavior known; change-ledger invalidation not implemented
* measured_bottleneck: warm catalog/detail quick; GENERAL 25.6s observed; serialization/frontend render/provider call metrics UNKNOWN/NOT_EXECUTED

### DB
* DBeaver connection: container/host/ports/db/user/password source/SSL as already documented
* schemas: public
* tables: poc_state, poc_catalog_embedding
* migrations: POC init SQL; backend Alembic separate
* secrets_exposed: NO

### CR_AND_ACCESS
* states: current legal states and exact user presentation mapping
* revision: round/current_round/revision evidence exists and must remain
* current role model: runtime one active ADMIN; required roles admin/data_steward/developer/viewer
* system assignment: runtime zero; required admin all, steward/developer assigned only, viewer read-only
* permission gaps: current target-scope enforcement and configured assignment policy not verified/needs T06
* proposed stage mapping:
  접수 완료=REGISTERED + initial IN_REVIEW
  재검토=CHANGES_REQUESTED + resubmitted IN_REVIEW using round/revision/transition
  변경/Test=TESTING/APPLY_QUEUED/APPLYING/APPLY_FAILED
  완료검토=FINAL_REVIEW
  완료=APPLIED/COMPLETED
  제외=REJECTED/CANCELLED
  presentation only, no domain state change

### PROPOSED_ARCHITECTURE
* exact capture/nightly reconciliation/current snapshot/change ledger/dedup/retention/timezone/assignee policy/CR link as supplied; explicitly PROVISIONAL pending T02
* no new DB/container/framework

### TASK_DAG
| task_id | owner | risk | depends_on | base_sha | allowed_paths | acceptance_criteria | required_validation |
|---|---|---|---|---|---|---|---|
| T00 | 10 | R2 | NONE | 78e533d | N/A | 완료됨 | 읽기 전용 조사 완료 |
| T01 | 40 | R2 | NONE | 78e533d | N/A | 타겟 프로브 차단 상태 완료 | 읽기 전용 조사 |
| T02 | 10 | R3 | T00, T01, TARGET_READ_ONLY_PROBE | UNKNOWN (to be assigned after probe) | docs/adr/0123-datahub-change-history-ledger.md | 소스 결정, 모델, 체크포인트, 일정, API 등 도출 | G1 integration |
| T03 | 40 | R3 | T02 | exact candidate SHA assigned at dispatch | T02 must enumerate | 백엔드 빌드/마이그레이션 | 유닛 테스트, G1 |
| T04 | 40 | R2 | T02, T03 | exact candidate SHA assigned at dispatch | T02 must enumerate | 정확한 캡처 구현 | 중간 이벤트, 멱등성 검증, G1 |
| T05 | 40 | R2 | T02, T03 | exact candidate SHA assigned at dispatch | T02 must enumerate | 조정(reconciliation)/성능 확보 | 성능 테스트, Redis 폴백, G1 |
| T06 | 30 | R3 | T02, T03 | exact candidate SHA assigned at dispatch | T02 must enumerate | 접근 제어/CR API 구현 | 10_ARCHITECTURE 리뷰, G1 |
| T07 | 60 | R2 | T05, T06 | exact candidate SHA assigned at dispatch | T02 must enumerate | 네이티브 모니터링/CR 주간 테이블 | 외부 탭 회귀 테스트, G1 |
| T08 | 50 | R3 | T04-T07 | exact candidate SHA assigned at dispatch | T02 must enumerate | 독립적 검증 완료 | 수정 불가 (no repair) |
| T09 | 90 | R3 | T08 | exact candidate SHA assigned at dispatch | T02 must enumerate | 감사 완료 | 수정 불가 (do not repair) |

### BLOCKERS
- Target-connected read-only Timeline/MCL evidence
- POLICY_CONFLICT prep-update points to forbidden datariver_v1; no access
- G1-G4 NOT_APPROVED
- No target role/system assignment evidence
- No new container approved/needed; if later required separate report

### NOT_EXECUTED
product code mutation/tests/build; authenticated Timeline data query; MCL topic/schema/offset probe; DataHub/Airflow/MinIO/Neo4j/Kafka mutation; migration; merge; push; PREP/OPS mutation; E2E/load test.
