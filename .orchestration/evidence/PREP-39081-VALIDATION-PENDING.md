# PREP-39081-VALIDATION-PENDING

## 외부 실행 증거

- environment: `PREP_WSL_AMD64`
- published SHA: `03fcacb933b0d837f3b6b6917c2754cc80e07673`
- execution actor: `USER_EXECUTED`
- evidence scope: `PREP_USER_REPORTED_EXTERNAL`
- existing service: `39080` 유지
- candidate service: `39081` 기동 성공
- current status: `PREP_CANDIDATE_RUNNING / VALIDATION_PENDING`
- Agent execution: `NOT_EXECUTED`
- PREP 판정: 사용자의 아래 결과가 도착하기 전까지 `PASS`로 승격하지 않음

## PREP_DEPLOYMENT_DRIFT

PREP의 local-only `Dockerfile.local`에는 tracked `Dockerfile.example`에 추가된
`poc-change-history-scheduler.mjs`와 `poc-mcl-capture.mjs` COPY가 없어서 첫 기동이 실패했다.
사용자가 `Dockerfile.local`만 최소 보완한 뒤 39081 기동에 성공했다. PREP 기본 검증 후
tracked Dockerfile 공통 사용 또는 local Dockerfile release drift check 중 최소안을 선택한다.

## PREP Base Validation Checklist

| 영역 | 확인 항목 | 기대 결과 | 사용자 결과 |
|---|---|---|---|
| Platform | 기존 39080 서비스 | 기존 기능과 health가 유지되고 중단되지 않음 | |
| Platform | candidate 39081 health | candidate health endpoint가 정상 응답 | |
| Platform | candidate exact SHA | 실행 소스의 `git rev-parse HEAD`가 `03fcacb933b0d837f3b6b6917c2754cc80e07673` | |
| Search / Catalog | 첫 Search 진입 | 오류·무한 로딩 없이 실데이터 결과가 표시됨 | |
| Search / Catalog | Search 재진입 | 동일 조건의 warm 진입이 정상이며 첫 진입보다 느려지지 않음 | |
| Search / Catalog | 검색 결과 | 검색어와 관련된 Table/View 및 match 근거가 표시됨 | |
| Search / Catalog | Resource Tree | 실제 Platform→Database→Schema→Table 계층을 탐색할 수 있음 | |
| Search / Catalog | Table/View Detail | 선택한 자산의 상세 Drawer가 열리고 사라지지 않음 | |
| Search / Catalog | 최신 Column/Metadata | DataHub의 현재 Column/설명/Tag/Term/Owner 정보와 일치함 | |
| Search / Catalog | 체감 성능 | 첫 진입과 재진입 모두 업무 사용을 막는 지연·멈춤이 없음 | |
| Existing Regression | Dashboard | 기존 Dashboard가 오류 없이 표시되고 실데이터/장애 상태를 구분함 | |
| Existing Regression | Registration | Manual/BULK 화면과 기존 동작이 회귀하지 않음 | |
| Existing Regression | Chat GENERAL | 일반 질문이 정상 응답함 | |
| Existing Regression | Chat VECTOR | 근거 기반 semantic 검색이 정상 응답함 | |
| Existing Regression | Chat GRAPH | 계보/관계 질문이 정상 응답하거나 provider 장애를 정직하게 표시함 | |
| Existing Regression | Quality | 품질 화면이 오류·더미 데이터 없이 기존 계약대로 표시됨 | |
| Existing Regression | Governance | 문서 화면과 기존 CRUD 진입 흐름이 회귀하지 않음 | |
| Existing Regression | Glossary | 용어 및 적용 자산 화면이 정상 표시됨 | |
| Existing Regression | Knowledge | Knowledge Studio 화면과 기존 기능 진입이 정상임 | |
| Change Management / Admin | User 관리 | 사용자 목록/관리 화면이 정상 표시됨 | |
| Change Management / Admin | System 관리 | 시스템 및 담당자 관리 화면이 정상 표시됨 | |
| Change Management / Admin | 주차별 변경 요약 | 변경관리 상단에 KST 주차 기준 표가 오류 없이 표시됨 | |
| Change Management / Admin | CR 상세 reverse history | CR 상세의 연결된 변경 이력이 읽기 전용으로 정상 표시됨 | |
| Monitoring | 첫/default tab | 첫 탭이 native `데이터 변경현황`이며 기본 활성 상태임 | |
| Monitoring | 정상 0건 상태 | provider/sync 오류가 아닌 유효한 0건 상태로 표시됨 | |
| Monitoring | 기존 Grafana/external tabs | 기존 외부 탭이 유지되고 구성된 탭을 열 수 있음 | |

## MCL/Scheduler Validation Checklist

이 단계는 PREP 기본 UI/Search 검증 완료 후에만 수행한다. 명령은 credential 값을 출력하지
않으며 `<candidate-web-container>`, `<kafka-container>`, `<postgres-container>`는 PREP의 실제 이름으로
치환한다.

| 체크 항목 | 검증 명령/판단 기준 | 상태 |
|---|---|---|
| Kafka advertised listener | `docker inspect <kafka-container>`에서 listener를 확인하고 `<candidate-web-container>`에서 `POC_MCL_KAFKA_BROKERS`의 broker metadata까지 도달; host-only 주소 광고 금지 | PENDING |
| Schema Registry URL | `<candidate-web-container>`에서 `POC_MCL_SCHEMA_REGISTRY_URL`의 `/subjects` 조회가 성공하고 credential은 출력하지 않음 | PENDING |
| MCL topic | `POC_MCL_KAFKA_TOPIC=MetadataChangeLog_Versioned_v1`, Schema Registry subject `MetadataChangeLog_Versioned_v1-value` 존재 | PENDING |
| 필요한 env delta | `deploy/poc/.env.example`의 `POC_CHANGE_HISTORY_*`와 `POC_MCL_*` 키를 기준으로 PREP `.env`의 SET/EMPTY만 비교하고 값은 출력하지 않음 | PENDING |
| scheduler enable | `POC_CHANGE_HISTORY_SCHEDULER_ENABLED=true`, `POC_CHANGE_HISTORY_SCHEDULER_TIME_ZONE=Asia/Seoul`; 나머지 필수 MCL binding이 모두 non-empty | PENDING |
| 안전한 metadata 변경 1건 | 식별 가능한 PREP 테스트 자산에 승인된 Tag 1건을 추가하고 asset URN·시각·Tag 이름을 기록 | PENDING |
| checkpoint 생성/전진 | `SELECT topic_contract, source_partition, first_exact_offset, next_offset, last_captured_at, version FROM poc_change_history_checkpoints ORDER BY source_partition;`에서 대상 partition checkpoint가 생성되고 변경 후 전진 | PENDING |
| MCL → ledger | `SELECT event_identity, source_aspect, category, operation, source_partition, source_offset, source_occurred_at, captured_at FROM poc_change_history_ledger_events ORDER BY captured_at DESC LIMIT 5;`에 방금 변경이 정확히 1회 저장 | PENDING |
| Monitoring +1 | native `데이터 변경현황`의 해당 category 총 건수가 기준값 대비 +1 | PENDING |
| 미진행 +1 | primary CR link 전에는 미진행 건수가 기준값 대비 +1 | PENDING |
| CR link | 허용된 사용자로 해당 change를 테스트 CR에 primary/candidate 계약대로 연결하고 기존 CR state는 불변 | PENDING |
| reverse history | CR 상세 reverse history에 연결/해제 actor·시각·사유가 표시 | PENDING |
| replay/dedup | 같은 boundary로 candidate를 재시작해 catch-up을 다시 수행한 뒤 ledger count와 event identity는 중복되지 않고 checkpoint는 후퇴하지 않음 | PENDING |
| KST scheduler/catch-up | HTTP manual trigger는 제공하지 않으므로 startup catch-up으로 검증; KST 00:00 boundary receipt가 1회만 생성되고 중복 실행이 없음 | PENDING |

## 진급 기준

- `PASS`: 기존 기능과 신규 UI가 정상이며 blocker 없음
- `PASS_WITH_DEBT`: 사용자 핵심 흐름을 막지 않는 UX/성능 debt만 존재
- `BLOCKED`: Search/Detail 실패, 기존 기능 regression, 권한 우회, Change Management/Monitoring 오류 또는 DB/runtime failure
- 사용자가 결과를 반환하기 전까지는 `PASS` 처리하지 않음

## 배포 편차 처리 후보

PREP 검증 후 다음 중 최소안을 선택한다.

1. tracked `Dockerfile.example` 공통 사용
2. `Dockerfile.local` 유지 시 tracked runtime COPY closure와 비교하는 release drift check 추가
