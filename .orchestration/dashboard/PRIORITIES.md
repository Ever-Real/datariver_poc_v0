# 현재 우선순위 대시보드 (POST-B01 DEV 체크포인트)

기준 증적 HEAD는 `0bc06a3351f466b6d8e8674acec8798c6df5a487`이다. 제품 후보는
`138044ab8f819e3bc86d09a9d4d25d3d421b0141`이며, `4deb4de..138044a` 사이에는 제품 코드 변경이
없고 `.orchestration/**` 증적만 추가되었다. `VALIDATION_PASS`는 소스/독립 검증 통과,
`RUNTIME_VERIFIED`는 실제 DEV 런타임에서 해당 범위를 확인했다는 뜻이다. 전체 기능 또는 단계가
런타임에서 확인되지 않았으면 `RUNTIME_VERIFIED`로 승격하지 않는다.

## 현재 판정

`DEV_INTEGRATION_CHECKPOINT_01 = BLOCKED`이다. Search/Catalog의 읽기 전용 범위는 Node 22에서
`PASS_WITH_LIMITATIONS` 및 `RUNTIME_VERIFIED`로 승격되었지만, MCL/Scheduler는 binding 0/9,
scheduler disabled, Kafka protocol/admin 실패, ledger/checkpoint 0으로 `BLOCKED_RUNTIME`이다.
실제 metadata mutation은 실행하지 않았다. B-02는 shutdown/restart blocker가 아니므로 수정하지
않는다. T08/T09는 체크포인트 전체 해소 전 대기한다.

Fixture 복구 후 `39083`은 healthy이고 active subject가 복구되었다. access/events/weekly API는
각각 4-role·2-system 200, empty 200, KST 주간 empty 200으로 독립 검증되었다. MCL required
binding은 nonblank `0/9`, scheduler는 disabled이므로 실제 event 기반 T06/T07은 계속
`BLOCKED_DEPENDENCY`/`NOT_EXECUTED`다. local Orca terminal credential exposure는 `YES`로 기록하되
값은 기록하지 않으며, external publication은 `NO`, rotation은 `NOT_EXECUTED`(별도 승인 필요)다.

## 작업 상태

| Task | 담당 기능 / 핵심 Action | 사용자가 보는 기능 | 실제 상태 | Runtime 확인 | Owner | Risk | Next |
|---|---|---|---|---|---|---|---|
| T00 | 기준선·통제·DAG | 일관된 작업 기준 | IMPLEMENTED | 소스 문서 | 10 | R2 | 감사 전 유지 |
| T01 | DataHub Timeline/MCL 능력 조사 | 변경 이력 보장 범위 | IMPLEMENTED | TARGET_RECHECK_REQUIRED | 40 | R2 | 릴리스 전 재확인 |
| T02 | Timeline 백필/MCL 전진 캡처 결정 | 정밀도 표기가 있는 이력 | IMPLEMENTED | 미실행 | 10 | R3 | T09 감사 |
| T03-PYTHON | Python/Alembic 원장 | 영속 변경 이력 기반 | VALIDATION_PASS | NOT_RUNTIME_INTEGRATED | 40 | R3 | Node 경로 포함 여부 별도 판정 |
| T03N | Node ledger/checkpoint 영속성 | 재시작 후 이력 보존 | VALIDATION_PASS | 테이블 존재, rows 0 | 40 | R3 | T08 재검증 |
| T04 | MCL decode·normalize·dedup·checkpoint | 정확한 변경 사건 | VALIDATION_PASS | BLOCKED_RUNTIME: binding 0/9, Kafka protocol 실패, ledger/checkpoint 0 | 40 | R3 | 운영 경계 설정 후 재실행 |
| SCHEDULER | KST 00:00·catch-up·중복 방지 | 자동 동기화 | VALIDATION_PASS | BLOCKED_RUNTIME: disabled, receipt 0, catch-up 미실행 | 40 | R2 | 설정 후 manual/catch-up |
| T05 | current projection·cache·성능·삭제 처리 | Search/Tree/Detail 최신성 | IMPLEMENTED | Search/Catalog 범위 PASS_WITH_LIMITATIONS·Node22 RUNTIME_VERIFIED; Redis/upstream 관측 제한 | 40 | R2 | T08 성능/관측 부채 |
| T06A | user/role/system/담당자 권위 | 관리자·범위 관리 | VALIDATION_PASS | fixture·claim spoof 차단만 확인; populated scope BLOCKED_DEPENDENCY | 30 | R3 | event/role fixture 후 재검증 |
| T06B | CR link/unlink·reverse history·weekly API | CR 연결·주간 집계 | VALIDATION_PASS | 빈 ledger/empty UI만 확인; 실제 link/weekly/reverse NOT_EXECUTED | 30 | R3 | event fixture 후 재검증 |
| T07 | Monitoring native·weekly·link UI | 이력 모니터링·CR 화면 | VALIDATION_PASS | native/empty state 확인; populated event/link BLOCKED_DEPENDENCY | 60 | R2 | 체크포인트 해소 후 T08 |
| T08 | 통합 E2E | 전체 제품 회귀·실제 흐름 | BLOCKED | 체크포인트 선행 | 50 | R3 | runtime blocker 해소 |
| T09 | fresh assurance audit | 최종 보증·권한·보존 감사 | BLOCKED | T08 미실행 | 90 | R3 | T08 후 |
| Search / Catalog / Tree / Detail | 현재 검색·트리·상세 및 B-01 projection | 카탈로그 탐색 | RUNTIME_VERIFIED | Node22 읽기 전용 PASS_WITH_LIMITATIONS; 2,000건·검색·Tree·유효 Detail 14/14 확인 | 40·60 | R2 | Redis/upstream 관측은 T08 |
| Current metadata sync | DataHub canonical → current projection/cache/vector | 최신 메타데이터 | BLOCKED | current projection 읽기는 확인했으나 Redis/upstream 호출·full freshness는 미확인 | 40 | R2 | T08 관측/재검증 |
| Schema / Metadata Change History | ledger 조회·보존·precision | 변경 이력 | IMPLEMENTED | rows 0, 실제 event 미수집; active subject fixture로 empty-state만 확인 | 40 | R3 | MCL 설정 후 |
| MCL capture / checkpoint | bounded Kafka MCL → ledger → checkpoint | 중간 변경 보존 | BLOCKED | BLOCKED_RUNTIME: binding 0/9, Kafka protocol 실패, ledger/checkpoint 0 | 40 | R3 | 운영 설정 후 |
| Scheduler / reconciliation | KST schedule·catch-up·reconciliation | 자동 갱신 | BLOCKED | BLOCKED_RUNTIME: disabled, durable receipt 0, catch-up 미실행 | 40 | R2 | 운영 설정 후 |
| User / Role 관리 | admin/steward/developer/viewer | 역할 관리 | VALIDATION_PASS | fixture API/claim 보호 확인 | 30 | R3 | populated action |
| System / 담당자 관리 | assignment·priority·fallback | 시스템 범위·담당자 | VALIDATION_PASS | fixture assignment만 확인 | 30 | R3 | positive scope |
| CR link/unlink / reverse history | primary/candidate/history | CR 추적 | VALIDATION_PASS | 빈 상태만 확인 | 30 | R3 | event fixture |
| Weekly Change Summary | server-side 주차 집계 | 주간 변경 표 | VALIDATION_PASS | 0건·7주 표 확인 | 60 | R2 | populated 집계 |
| Monitoring 데이터 변경현황 | native summary/filter/detail | 변경현황 탭 | VALIDATION_PASS | empty state/필터 확인 | 60 | R2 | populated detail |
| 기존 Grafana tabs | external monitoring 계약 유지 | 기존 모니터링 | DEFERRED | NOT_CONFIGURED | 20·60 | R2 | T08 |
| Registration Manual/BULK | DataHub/MinIO/Airflow 변경 | 등록관리 | DEFERRED | 종단 검증 미실행 | 40 | R3 | T08 이후 |
| Chat GENERAL/VECTOR/GRAPH | 근거 기반 chat·최신 projection | Chat | DEFERRED | 종단 검증 미실행 | 40 | R2 | T08 이후 |
| Quality | profile/assertion/GX | 품질관리 | DEFERRED | 미실행 | 30 | R3 | 기존 backlog |
| Governance | 문서 CRUD/version/safe render | 거버넌스 문서 | DEFERRED | 미실행 | 30 | R2 | 기존 backlog |
| Glossary | term hierarchy/asset assignment | 용어사전 | DEFERRED | 미실행 | 40 | R2 | 기존 backlog |
| Knowledge | asset/version/graph projection | Knowledge Studio | DEFERRED | 미실행 | 40 | R3 | 기존 backlog |
| Admin | user/system/permission/security UI | 관리자 메뉴 | DEFERRED | fixture API 일부만 확인 | 30 | R3 | T08 |
| 전체 E2E | 기존 기능 + Change History | 통합 인수 | BLOCKED | T08 대기 | 50 | R3 | checkpoint 후 |
| Release / PREP / OPS | artifact/checksum/이관 | 배포 | DEFERRED | 미실행, G1~G4 미승인 | 20 | R3 | T09·승인 후 |

## 즉시 우선순위

1. B-01은 `PASS_LOCAL_SOURCE`로 종료하며 추가 repair하지 않는다.
2. local `.env`/DataHub self-loop, Kafka listener·MCL 설정, checkpoint fixture cleanup은 별도 승인/NOTI 범위로 유지한다.
3. 위 runtime blocker 해소 후 같은 coherent candidate로 체크포인트를 재실행한다.
4. 체크포인트가 PASS 또는 PASS_WITH_DEBT일 때만 T08 → T09로 진행한다.

## 상태 구분 요약

- T03: `VALIDATION_PASS`, `RUNTIME_VERIFIED` 아님.
- T04: `VALIDATION_PASS`, 실제 MCL `RUNTIME_VERIFIED` 아님.
- SCHEDULER: `VALIDATION_PASS`, 계산만 runtime 관찰; trigger/catch-up `RUNTIME_VERIFIED` 아님.
- T05: `IMPLEMENTED`; 현재 catalog 전체 조건은 `RUNTIME_VERIFIED` 아님.
- T06: `VALIDATION_PASS`; populated role/action/link runtime은 `RUNTIME_VERIFIED` 아님.
- T07: `VALIDATION_PASS`; populated event/link runtime은 `RUNTIME_VERIFIED` 아님.

## 게이트

G1 `NOT_APPROVED` · G2 `NOT_APPROVED` · G3 `NOT_APPROVED` · G4 `NOT_APPROVED`
