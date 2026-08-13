# 현재 우선순위

일관된 증적 기준 HEAD는 `0a4c0a872c4fed56392c2e942eaeaeb62330aff5`, 제품 SHA는
`639a4830d7db2775b0932c58adb14ac6185f437c`, DEV 런타임 확인 후보는
`11632c9159ca97e5a7903789bf58cc884e1e7303`이다. `VALIDATION_PASS`는 소스 검증 통과만 뜻한다.
`RUNTIME_VERIFIED`는 위 DEV 후보에서 실제 제공자 경로를 확인했다는 뜻이며 배포·TARGET·게이트 승인을
뜻하지 않는다. 상태 값은 `NOT_STARTED`, `IN_PROGRESS`, `IMPLEMENTED`, `VALIDATION_PASS`,
`RUNTIME_VERIFIED`, `BLOCKED`, `DEFERRED`, `PENDING_AUDIT`만 사용한다.

## 최우선 5개

1. `T07`: 변경 이력 모니터링과 주간 CR 화면 구현을 시작한다.
2. `T06B-INDEPENDENT-VALIDATION`: KST 주간 경계 보수를 새 작업트리에서 독립 재검증한다.
3. `T08`: 카탈로그·이력·권한·화면을 독립 통합 검증한다.
4. `T09`: 전체 증적과 권위·보존·성능 경계를 감사한다.
5. `TARGET-RECHECK`: 보존 정책·MCL·Schema Registry의 실제 상태를 재확인한다.

## 작업 상태

| Task | 담당 기능 / 핵심 Action Item | 사용자가 보는 기능 | 실제 상태 | Owner | Risk | Dependency | Runtime 확인 |
|---|---|---|---|---|---|---|---|
| T00 | 조사 기준선과 통제 문서 확정 | 일관된 작업 기준 | IMPLEMENTED | 10 | R2 | 없음 | 미확인 |
| T01 | DEV 캡처 능력 조사와 후보 선택 | 변경 이력 제공 가능성 | IMPLEMENTED | 40 | R2 | TARGET-RECHECK | 과거 관찰만 있음; 현재 미확인 |
| T02 | MCL 전진 캡처와 Timeline 백필 결정 | 누락을 숨기지 않는 이력 정책 | IMPLEMENTED | 10 | R3 | TARGET-RECHECK, G1 | 제품 런타임 미실행 |
| T03-PYTHON | Python/Alembic 원장과 체크포인트 기반 | 감사 가능한 영속 이력 기반 | VALIDATION_PASS | 40 | R3 | T02, T09 | `NOT_RUNTIME_INTEGRATED`; Node 제품 경로와 연결되지 않음 |
| T03N | Node 원장 영속성; `PENDING_T09` | 재시작 뒤에도 남는 이력 | VALIDATION_PASS | 40 | R3 | T03-PYTHON, T09 | 실제 PostgreSQL 원장 append·충돌 검증 미실행 |
| T04 | MCL 캡처·중복 제거·체크포인트·누락 구간 경계; `PENDING_T09` | 정확도 표기가 있는 변경 사건 | VALIDATION_PASS | 40 | R3 | T03N, TARGET-RECHECK, T09 | MCL 실제 캡처 미실행; 필수 연결 설정 0/9 |
| SCHEDULER | KST 일일 실행·단일 실행·오래된 작업 차단; `PENDING_T09` | 자동 변경 이력 갱신 | VALIDATION_PASS | 40 | R2 | T04, T09 | 비활성 상태로 실제 따라잡기 실행 미실행 |
| T05 | 현재상태 투영·원자 교체·삭제·캐시·벡터 세대 차단·성능; `PENDING_T09` | 최신 카탈로그 검색·트리·상세 | RUNTIME_VERIFIED | 40 | R2 | T03N, T09 | DEV 실제 제공자 초기·재시작 경로에서 정확히 2,000건과 검색·트리·상세 확인 |
| T06A-USER-SYSTEM | 관리자·역할·담당자와 User/System 권위; `PENDING_T09` | 관리자 범위 설정과 담당자별 접근 | VALIDATION_PASS | 30 | R3 | T03N, T09 | 실제 서비스 주체·PostgreSQL 통합 미실행 |
| T06B-CR | 사건 조회·CR 연결/해제·KST 주간 집계; `PENDING_T09` | CR 연결 이력과 주간 현황 | IMPLEMENTED | 30 | R3 | T06A-USER-SYSTEM, 독립 재검증, T09 | KST 보수 자체 검증만 통과; 실제 PostgreSQL·DataHub 미실행 |
| PLATFORM-REPAIR | Docker `import`/`COPY`·환경 전달·빈 비밀 기본값 보수; `PENDING_T09` | 같은 설정으로 기동 가능한 패키지 | VALIDATION_PASS | 20 | R2 | DEV-INTEGRATION-CHECKPOINT-01-R1, T09 | 정적 설정 검증 완료; 이미지와 컨테이너 변경 미실행 |
| DEV-INTEGRATION-CHECKPOINT-01-R1 | 제품 SHA를 포함한 실제 제공자 DEV 체크포인트 | T07 착수용 신뢰 기준선 | RUNTIME_VERIFIED | 20·50 | R2 | T03N~T06B, PLATFORM-REPAIR | `PASS_WITH_DEBT`; 초기·재시작 기동과 카탈로그 핵심 경로 확인, 후보 프로세스 종료 |
| T07 | 변경 이력 내장 모니터링과 CR 주간 화면 구현 | 서비스 안의 이력·주간 대시보드 | NOT_STARTED | 60 | R2 | DEV-INTEGRATION-CHECKPOINT-01-R1 충족 | 저장소 구현 증적 없음; 다음 작업 |
| T08 | 카탈로그·이력·접근·화면 독립 통합 검증 | 오류·빈 상태·권한을 포함한 검증 흐름 | NOT_STARTED | 50 | R3 | T04~T07 | 선행 작업 대기; 미실행 |
| T09 | 최종 보증 감사 | 근거를 추적할 수 있는 승인 판단 | NOT_STARTED | 90 | R3 | T08, TARGET-RECHECK | 선행 작업 대기; 미실행 |
| CATALOG-CURRENT-METADATA | 검색·트리·상세·프로파일·리니지와 현재 메타데이터 회귀 | 최신 메타데이터 탐색 전반 | RUNTIME_VERIFIED | 40·60 | R2 | T05, T08 | DEV 서버 API의 카탈로그·검색 0건 경계·트리·상세 확인; 브라우저 미실행 |
| MONITORING | 환경 기반 Grafana와 기존 운영 화면 회귀 | 운영 상태와 지표 확인 | PENDING_AUDIT | 50·60 | R2 | T07, T08 | Grafana 미구성; 브라우저 미실행 |
| REGISTRATION | Manual·BULK·MinIO·Airflow·DataHub 재조회 회귀 | 단건·대량 메타데이터 등록 | PENDING_AUDIT | 40 | R3 | T08, 외부 제공자 | 부분 구현만 확인; 제공자 종단 검증 미실행 |
| CHAT | GENERAL·VECTOR·GRAPH·근거·세션 메모리 회귀 | 근거 기반 카탈로그 대화 | PENDING_AUDIT | 40 | R2 | T05, T08 | 대화·임베딩 제공자 가용성만 확인; 대화 기능·Neo4j 종단 검증 미실행 |
| QUALITY | DataHub 프로파일·검증 규칙·GX 연동 회귀 | 품질 상태와 실행 근거 | DEFERRED | 30 | R3 | T08, 실제 제공자 증거 | 성공 상태 신뢰성 감사 전; 미실행 |
| GOVERNANCE | 안전한 문서 CRUD·버전·검토·표시 회귀 | 거버넌스 문서 관리 | PENDING_AUDIT | 30 | R2 | T08 | 부분 구현만 확인; 브라우저 미실행 |
| GLOSSARY | DataHub 계층과 테이블·컬럼 연결 회귀 | 용어집 탐색과 자산 연결 | PENDING_AUDIT | 40 | R2 | T08, DataHub | 부분 구현만 확인; 제공자 기능 미실행 |
| KNOWLEDGE | 초안·버전·보관·DataHub/Neo4j 투영 회귀 | Knowledge Studio | DEFERRED | 40 | R3 | T08, 증적 의미 보수 | 성공·해시 신뢰 위험 미해소; 미실행 |
| ADMIN | 회원·권한 카탈로그·보안·보존 설정 회귀 | 관리자 설정 화면 | PENDING_AUDIT | 30 | R3 | T06A-USER-SYSTEM, T08 | 부분 구현만 확인; 영속 런타임 미실행 |
| TARGET-RECHECK | 보존 정책·MCL 토픽/파티션·Schema Registry 주제/스키마 재측정 | 보장 가능한 이력 범위 | BLOCKED | 20·50 | R3 | TARGET 읽기 권한 | 현재 TARGET 증적 없음 |
| PREP | 소스·산출물·체크섬·Node 22·Linux AMD64 검증 | 준비 환경에서 재현 가능한 배포 | BLOCKED | 20 | R3 | T08, G3 | 미실행 |
| OPS | PREP 승인 산출물의 운영 검증 | 운영 환경 배포 판단 | BLOCKED | 20 | R3 | PREP, G4 | 미실행 |

## 실행 체크리스트

- [x] T03 Python 비통합과 T03N Node 소스 검증을 분리했다.
- [x] T04 MCL과 SCHEDULER의 소스 검증 통과를 실제 런타임 실행과 분리했다.
- [x] DEV 실제 제공자 체크포인트에서 T05 카탈로그·검색·트리·상세와 재시작 경계를 확인했다.
- [x] 선택형 Redis 인벤토리 키 부재와 LLM Reranker `PROBE_FAILED`를 비차단 기술 부채로 유지했다.
- [ ] T07을 착수하고 T06B KST 보수를 독립 재검증한 뒤 T08, T09 순서로 진행한다.
- [ ] TARGET-RECHECK와 G1~G4 승인 전 PREP·OPS를 실행하지 않는다.

## 다음 3개

1. `T07`
2. `T06B-INDEPENDENT-VALIDATION`
3. `T08`

## 대표 근거

- [T03N 독립 검증](../evidence/CHANGE-HIST-T03N-INDEPENDENT-VALIDATION.md)
- [T04 보수 독립 재검증](../evidence/CHANGE-HIST-T04-REPAIR-01-REVALIDATION.md)
- [SCHEDULER 보수 독립 검증](../evidence/CHANGE-HIST-SCHEDULER-REPAIR-01-VALIDATION.md)
- [T05 R3 독립 검증](../evidence/CHANGE-HIST-T05-R3-INDEPENDENT-VALIDATION.md)
- [T06A 독립 재검증](../evidence/CHANGE-HIST-T06A-REVALIDATION.md)
- [T06B 보수 자체 검증](../evidence/CHANGE-HIST-T06B-REPAIR-01.md)
- [DEV 실제 제공자 체크포인트](../evidence/DEV-INTEGRATION-CHECKPOINT-01-R1.md)
- [DEV 체크포인트 구조화 영수증](../receipts/DEV-INTEGRATION-CHECKPOINT-01-R1.json)

## DEV 체크포인트 잔여 기술 부채

- 선택형 Redis 인벤토리 키는 없었고 PostgreSQL 현재 투영이 권위 원본으로 동작했다.
- LLM Reranker는 `unavailable / PROBE_FAILED`였다.
- MCL 캡처와 스케줄러 따라잡기 실행은 설정이 없어 `NOT_EXECUTED`였다.
- MinIO와 Grafana는 `NOT_CONFIGURED`였고 제공자·컨테이너·기존 39080 런타임은 변경하지 않았다.

## 게이트

G1: NOT_APPROVED, G2: NOT_APPROVED, G3: NOT_APPROVED, G4: NOT_APPROVED

현재 G1~G4 게이트는 승인되지 않았다.
