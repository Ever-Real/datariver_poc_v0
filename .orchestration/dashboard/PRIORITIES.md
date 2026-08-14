# 현재 우선순위 대시보드 (PREP-39081)

기준 증적 HEAD 및 제품 후보는 `03fcacb933b0d837f3b6b6917c2754cc80e07673`이다.
현재 상태는 PREP RUNNING 및 VALIDATION_PENDING이며, 추가 검증(T08/T09)은 HOLD 상태이다.
`VALIDATION_PASS`는 소스/독립 검증 통과, `RUNTIME_VERIFIED`는 실제 타겟 런타임에서 범위를 확인했다는 뜻이다.
전체 기능 또는 단계가 런타임에서 확인되지 않았으면 `RUNTIME_VERIFIED`로 승격하지 않는다.

## 현재 판정

현재 PREP-39081 후보가 RUNNING 상태이며, 사용자 환경 검증(VALIDATION_PENDING)을 대기 중이다.
MCL/Scheduler 검증 및 추가 통합/종단 테스트(T08/T09)는 PREP_WSL_AMD64 환경에서의 검증 결과가 반환될 때까지 HOLD 상태로 대기한다.

## 작업 상태

| Task | 담당 기능 | 사용자 기능 | 구현 상태 | DEV Runtime | PREP Runtime | Next |
|---|---|---|---|---|---|---|
| T00 | 기준선·통제·DAG | 일관된 작업 기준 | IMPLEMENTED | 소스 문서 | 39081 running/validation pending | 감사 전 유지 |
| T01 | DataHub Timeline/MCL 능력 조사 | 변경 이력 보장 범위 | IMPLEMENTED | TARGET_RECHECK_REQUIRED | 39081 running/validation pending | 릴리스 전 재확인 |
| T02 | Timeline 백필/MCL 전진 캡처 결정 | 정밀도 표기가 있는 이력 | IMPLEMENTED | 미실행 | 39081 running/validation pending | T09 감사 |
| T03-PYTHON | Python/Alembic 원장 | 영속 변경 이력 기반 | VALIDATION_PASS | NOT_RUNTIME_INTEGRATED | 39081 running/validation pending | Node 경로 포함 여부 별도 판정 |
| T03N | Node ledger/checkpoint 영속성 | 재시작 후 이력 보존 | VALIDATION_PASS | 테이블 존재, rows 0 | 39081 running/validation pending | T08 재검증 |
| T04 | MCL decode·normalize·dedup·checkpoint | 정확한 변경 사건 | VALIDATION_PASS | BLOCKED_RUNTIME: binding 0/9, Kafka protocol 실패, ledger/checkpoint 0 | 39081 running/validation pending | 운영 경계 설정 후 재실행 |
| SCHEDULER | KST 00:00·catch-up·중복 방지 | 자동 동기화 | VALIDATION_PASS | BLOCKED_RUNTIME: disabled, receipt 0, catch-up 미실행 | 39081 running/validation pending | 설정 후 manual/catch-up |
| T05 | current projection·cache·성능·삭제 처리 | Search/Tree/Detail 최신성 | IMPLEMENTED | Search/Catalog 범위 PASS_WITH_LIMITATIONS·Node22 RUNTIME_VERIFIED; Redis/upstream 관측 제한 | 39081 running/validation pending | T08 성능/관측 부채 |
| T06A | user/role/system/담당자 권위 | 관리자·범위 관리 | VALIDATION_PASS | fixture·claim spoof 차단만 확인; populated scope BLOCKED_DEPENDENCY | 39081 running/validation pending | event/role fixture 후 재검증 |
| T06B | CR link/unlink·reverse history·weekly API | CR 연결·주간 집계 | VALIDATION_PASS | 빈 ledger/empty UI만 확인; 실제 link/weekly/reverse NOT_EXECUTED | 39081 running/validation pending | event fixture 후 재검증 |
| T07 | Monitoring native·weekly·link UI | 이력 모니터링·CR 화면 | VALIDATION_PASS | native/empty state 확인; populated event/link BLOCKED_DEPENDENCY | 39081 running/validation pending | 체크포인트 해소 후 T08 |
| T08 | 통합 E2E | 전체 제품 회귀·실제 흐름 | HOLD | 체크포인트 선행 | 39081 running/validation pending | 사용자 PREP 결과 후 별도 지시 대기 |
| T09 | fresh assurance audit | 최종 보증·권한·보존 감사 | HOLD | T08 미실행 | 39081 running/validation pending | T08 후 별도 지시 대기 |
| Search / Catalog / Tree / Detail | 현재 검색·트리·상세 및 B-01 projection | 카탈로그 탐색 | RUNTIME_VERIFIED | Node22 읽기 전용 PASS_WITH_LIMITATIONS; 2,000건·검색·Tree·유효 Detail 14/14 확인 | 39081 running/validation pending | Redis/upstream 관측은 T08 |
| Current metadata sync | DataHub canonical → current projection/cache/vector | 최신 메타데이터 | BLOCKED | current projection 읽기는 확인했으나 Redis/upstream 호출·full freshness는 미확인 | 39081 running/validation pending | T08 관측/재검증 |
| Schema / Metadata Change History | ledger 조회·보존·precision | 변경 이력 | IMPLEMENTED | rows 0, 실제 event 미수집; active subject fixture로 empty-state만 확인 | 39081 running/validation pending | MCL 설정 후 |
| MCL capture / checkpoint | bounded Kafka MCL → ledger → checkpoint | 중간 변경 보존 | BLOCKED | BLOCKED_RUNTIME: binding 0/9, Kafka protocol 실패, ledger/checkpoint 0 | 39081 running/validation pending | 운영 설정 후 |
| Scheduler / reconciliation | KST schedule·catch-up·reconciliation | 자동 갱신 | BLOCKED | BLOCKED_RUNTIME: disabled, durable receipt 0, catch-up 미실행 | 39081 running/validation pending | 운영 설정 후 |
| User / Role 관리 | admin/steward/developer/viewer | 역할 관리 | VALIDATION_PASS | fixture API/claim 보호 확인 | 39081 running/validation pending | populated action |
| System / 담당자 관리 | assignment·priority·fallback | 시스템 범위·담당자 | VALIDATION_PASS | fixture assignment만 확인 | 39081 running/validation pending | positive scope |
| CR link/unlink / reverse history | primary/candidate/history | CR 추적 | VALIDATION_PASS | 빈 상태만 확인 | 39081 running/validation pending | event fixture |
| Weekly Change Summary | server-side 주차 집계 | 주간 변경 표 | VALIDATION_PASS | 0건·7주 표 확인 | 39081 running/validation pending | populated 집계 |
| Monitoring 데이터 변경현황 | native summary/filter/detail | 변경현황 탭 | VALIDATION_PASS | empty state/필터 확인 | 39081 running/validation pending | populated detail |
| 기존 Grafana tabs | external monitoring 계약 유지 | 기존 모니터링 | DEFERRED | NOT_CONFIGURED | 39081 running/validation pending | T08 |
| Registration Manual/BULK | DataHub/MinIO/Airflow 변경 | 등록관리 | DEFERRED | 종단 검증 미실행 | 39081 running/validation pending | T08 이후 |
| Chat GENERAL/VECTOR/GRAPH | 근거 기반 chat·최신 projection | Chat | DEFERRED | 종단 검증 미실행 | 39081 running/validation pending | T08 이후 |
| Quality | profile/assertion/GX | 품질관리 | DEFERRED | 미실행 | 39081 running/validation pending | 기존 backlog |
| Governance | 문서 CRUD/version/safe render | 거버넌스 문서 | DEFERRED | 미실행 | 39081 running/validation pending | 기존 backlog |
| Glossary | term hierarchy/asset assignment | 용어사전 | DEFERRED | 미실행 | 39081 running/validation pending | 기존 backlog |
| Knowledge | asset/version/graph projection | Knowledge Studio | DEFERRED | 미실행 | 39081 running/validation pending | 기존 backlog |
| Admin | user/system/permission/security UI | 관리자 메뉴 | DEFERRED | fixture API 일부만 확인 | 39081 running/validation pending | T08 |
| 전체 E2E | 기존 기능 + Change History | 통합 인수 | HOLD | T08 대기 | 39081 running/validation pending | 사용자 PREP 결과 후 별도 지시 대기 |
| Release / PREP / OPS | artifact/checksum/이관 | 배포 | PREP TEST PUBLISHED | G1/G2로 03fcacb publication 완료 | 39080 유지·39081 running/validation pending | G3/G4 NOT_APPROVED; 교체/OPS 금지 |

## 즉시 우선순위

1. 사용자가 39081에서 PREP 기본 검증 체크리스트를 수행하고 결과를 반환한다.
2. 기본 검증 이후에만 PREP MCL/Scheduler 검증을 별도 phase로 준비한다.
3. `PREP_DEPLOYMENT_DRIFT`는 검증 후 tracked Dockerfile 공통 사용 또는 drift check 중 최소안으로 처리한다.
4. T08/T09와 추가 publication은 HOLD하며, 39080 교체와 G3/G4는 별도 사용자 승인이 필요하다.

## 상태 구분 요약

- T03: `VALIDATION_PASS`, `RUNTIME_VERIFIED` 아님.
- T04: `VALIDATION_PASS`, 실제 MCL `RUNTIME_VERIFIED` 아님.
- SCHEDULER: `VALIDATION_PASS`, 계산만 runtime 관찰; trigger/catch-up `RUNTIME_VERIFIED` 아님.
- T05: `IMPLEMENTED`; 현재 catalog 전체 조건은 `RUNTIME_VERIFIED` 아님.
- T06: `VALIDATION_PASS`; populated role/action/link runtime은 `RUNTIME_VERIFIED` 아님.
- T07: `VALIDATION_PASS`; populated event/link runtime은 `RUNTIME_VERIFIED` 아님.

## 게이트

G1 `APPROVED (03fcacb)` · G2 `APPROVED (03fcacb)` · G3 `NOT_APPROVED` · G4 `NOT_APPROVED`
