## 변경 이력 실행 계획 (CHANGE_HISTORY_EXECUTION_PLAN)

### 기준선 (BASELINE)
* exact_sha: 78e533db6db0352dc0b6d44a557db22a7b05162c (T00/T01 탐색을 위한 정확한 베이스)
* branch: dev / task 분기
* dirty_state: 탐색 워크트리는 clean 상태; dev는 계획 수립 전 동일 소유자의 하네스 원장 변경사항만 존재; 8bc8001 이후 clean 상태
* environment: DEV_MAC_ARM64

### 정확한 캡처 (EXACT_CAPTURE)
* timeline_internal_status: ENDPOINT_ADVERTISED_DATA_UNVERIFIED
* categories: 5개 카테고리 UNKNOWN
* retained_history: UNKNOWN
* retention_loss_risk: UNKNOWN
* mcl_status: INFRA_OBSERVED_TOPIC_SCHEMA_OFFSET_NOT_EXECUTED
* selected_candidate: UNDECIDED_PENDING_TARGET_PROBE
* selection_gap: 정확한 PREP/admin 증거 목록

### 현재 데이터 경로 (CURRENT_DATA_PATH)
* table_load_path: UI -> POC API -> GMS GraphQL; 필터 없는 직접 스크롤; 필터링된 전체 인벤토리
* DataHub_calls: 코드 패턴 페이지 250건 상한 10002건; 요청당 런타임 지표 없음
* Redis: 실제 설정됨, 15분 인벤토리/60초 자산 가속; 선택 사항
* PostgreSQL: 실제 설정됨, poc_state/current + poc_catalog_embedding
* pgvector: READY 2000 최신 세대
* current_projection: PostgreSQL 상태/벡터, DataHub 현재 상태 전용
* cache_invalidation: TTL 및 변경된 임베딩 동작 확인됨; 변경 원장 무효화는 구현되지 않음
* measured_bottleneck: warm 카탈로그/상세 정보는 빠름; Chat GENERAL에서 25.6초 관찰됨; 직렬화/프론트엔드 렌더링/공급자 호출 지표 UNKNOWN/NOT_EXECUTED

### 데이터베이스 (DB)
* DBeaver connection: 컨테이너/호스트/포트/DB/사용자/비밀번호 소스/SSL은 이미 문서화된 상태와 동일
* schemas: public
* tables: poc_state, poc_catalog_embedding
* migrations: POC 초기 SQL; 백엔드 Alembic 분리됨
* secrets_exposed: NO

### CR 및 접근 제어 (CR_AND_ACCESS)
* states: 현재 유효한 상태 및 정확한 사용자 화면 매핑
* revision: round/current_round/revision 증거가 존재하며 유지되어야 함
* current role model: 런타임에 1명의 활성 ADMIN; 필요 역할은 admin/data_steward/developer/viewer
* system assignment: 런타임에 0명; 필요 요건으로 admin은 전체, steward/developer는 할당된 항목만, viewer는 읽기 전용
* permission gaps: 현재 타겟 범위 강제 및 구성된 할당 정책 미검증/T06 필요
* proposed stage mapping:
  접수 완료=REGISTERED + 초기 IN_REVIEW
  재검토=CHANGES_REQUESTED + round/revision/transition을 사용하여 다시 제출된 IN_REVIEW
  변경/Test=TESTING/APPLY_QUEUED/APPLYING/APPLY_FAILED
  완료검토=FINAL_REVIEW
  완료=APPLIED/COMPLETED
  제외=REJECTED/CANCELLED
  표현 계층 전용이며 도메인 상태 변경 없음

### 제안된 아키텍처 (PROPOSED_ARCHITECTURE)
* 정확한 캡처/야간 조정(reconciliation)/현재 스냅샷/변경 원장/중복 제거(dedup)/보존/시간대/담당자 정책/CR 링크는 제공된 대로 적용; T02 이전까지 명시적으로 PROVISIONAL 상태
* 새로운 DB/컨테이너/프레임워크 없음

### 작업 DAG (TASK_DAG)
| 작업 ID (task_id) | 소유자 (owner) | 위험도 (risk) | 의존성 (depends_on) | 베이스 SHA (base_sha) | 허용 경로 (allowed_paths) | 수용 기준 (acceptance_criteria) | 필수 검증 (required_validation) |
|---|---|---|---|---|---|---|---|
| T00 | 10 | R2 | NONE | 78e533d | N/A | 완료됨 | 읽기 전용 조사 완료 |
| T01 | 40 | R2 | NONE | 78e533d | N/A | 타겟 프로브 차단 상태 완료 | 읽기 전용 조사 |
| T02 | 10 | R3 | T00, T01, TARGET_READ_ONLY_PROBE | UNKNOWN (프로브 이후 할당됨) | docs/adr/0123-datahub-change-history-ledger.md | 소스 결정, 모델, 체크포인트, 일정, API 등 도출 | G1 통합 |
| T03 | 40 | R3 | T02 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 백엔드 빌드/마이그레이션 | 유닛 테스트, G1 |
| T04 | 40 | R2 | T02, T03 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 정확한 캡처 구현 | 중간 이벤트, 멱등성 검증, G1 |
| T05 | 40 | R2 | T02, T03 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 조정(reconciliation)/성능 확보 | 성능 테스트, Redis 폴백, G1 |
| T06 | 30 | R3 | T02, T03 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 접근 제어/CR API 구현 | 10_ARCHITECTURE 리뷰, G1 |
| T07 | 60 | R2 | T05, T06 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 네이티브 모니터링/CR 주간 테이블 | 외부 탭 회귀 테스트, G1 |
| T08 | 50 | R3 | T04-T07 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 독립적 검증 완료 | 수정 불가 (no repair) |
| T09 | 90 | R3 | T08 | dispatch 시 할당된 정확한 후보 SHA | T02에서 열거해야 함 | 감사 완료 | 수정 불가 (do not repair) |

### 차단 요소 (BLOCKERS)
- 타겟에 연결된 읽기 전용 Timeline/MCL 증거
- POLICY_CONFLICT: prep-update가 금지된 datariver_v1을 가리킴; 접근 불가
- G1-G4 NOT_APPROVED
- 타겟 역할/시스템 할당 증거 없음
- 새로운 컨테이너 승인/필요 없음; 추후 필요할 경우 별도 보고서 작성

### 미실행 항목 (NOT_EXECUTED)
product code 변경(mutation)/테스트/빌드; 인증된 Timeline 데이터 쿼리; MCL topic/schema/offset 프로브; DataHub/Airflow/MinIO/Neo4j/Kafka 변경(mutation); 마이그레이션(migration); merge; push; PREP/OPS 변경(mutation); E2E/load test.
