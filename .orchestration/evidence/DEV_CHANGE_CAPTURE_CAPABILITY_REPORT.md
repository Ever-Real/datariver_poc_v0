## DEV_CHANGE_CAPTURE_CAPABILITY_REPORT

### TARGET_EVIDENCE
- **Timeline**: 타겟 환경에서 Timeline 엔드포인트 접근이 성공적으로 확인됨 (TARGET_USER_OBSERVED).
- **TECHNICAL_SCHEMA**: ADD 시맨틱 이벤트가 관찰됨 (TARGET_USER_OBSERVED).
- **DOCUMENTATION**: 변경 이력이 관찰됨 (TARGET_USER_OBSERVED).
- **TAG, GLOSSARY_TERM, OWNERSHIP**: NO_EVENT_OBSERVED, 해당 이벤트가 관찰되지 않았으나 UNSUPPORTED 상태는 아님 (TARGET_USER_OBSERVED).
- **retained_history**: metadata_aspect_v2에 여러 애스펙트 이력이 보관되어 있으며, 최대 948까지의 버전 인덱스가 관찰됨 (TARGET_USER_OBSERVED).

### DEV_RETENTION
- **enabled**: `true` (`ENTITY_SERVICE_ENABLE_RETENTION=true` 확인) (DEV_OBSERVED).
- **effective_environment**: `DEV` (DEV_OBSERVED).
- **bundled_default**: `ENTITY_SERVICE_ENABLE_RETENTION=true` 및 `APPLY_RETENTION_BOOTSTRAP=false`가 기본값임 ([environment-vars.md](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/deploy/environment-vars.md) 참조) (SOURCE_CONFIRMED).
- **custom_policy**: `NOT_OBSERVED` (별도 정책 적용 미확인).
- **max_versions**: `UNKNOWN`.
- **time_based_policy**: `UNKNOWN`.
- **plugin_path**: `RETENTION_PLUGIN_PATH` (공식 문서 기준) 확인 불가 (`NOT_OBSERVED`) (SOURCE_CONFIRMED).
- **system_update_evidence**: `UNKNOWN`.
- **representative_retained_versions**: `datasetProperties` (최대 버전 2, 3005건), `globalTags` (최대 버전 2, 3005건), `glossaryTerms` (최대 버전 1, 2003건), `schemaMetadata` (최대 버전 1, 2003건) (DEV_OBSERVED).
- **oldest_observed_timestamp**: `2026-07-20 05:55:32` (DEV_OBSERVED).
- **daily_poll_loss_risk**: Retention 정책에 의해 오래된 이력이 폴링 전 삭제될 위험 존재 ([environment-vars.md](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/deploy/environment-vars.md) 참조) (SOURCE_CONFIRMED).
- **normal_daily_poll**: `INSUFFICIENT_EVIDENCE`.
- **high_change_asset**: `INSUFFICIENT_EVIDENCE`.
- **one_day_outage**: `INSUFFICIENT_EVIDENCE`.
- **multi_day_outage**: `INSUFFICIENT_EVIDENCE`.
- **exact_capture_guarantee**: `INSUFFICIENT_EVIDENCE`.
- **required_overlap**: `UNKNOWN`.
- **recommendation**: TARGET MCL/retention 상태 재확인 필요 (TARGET_RECHECK_REQUIRED).

### DEV_MCL
- **topic**: `MetadataChangeLog_Versioned_v1` (DEV_OBSERVED).
- **topic offsets**: 50340 (`generic-mae-consumer-job-client` 기준 LOG-END-OFFSET) (DEV_OBSERVED).
- **partitions**: 1 파티션 (DEV_OBSERVED).
- **schema_registry image+version**: `datahub-schema-registry-1` 내 `cp-schema-registry:7.9.2` (DEV_OBSERVED).
- **subjects**: `MetadataChangeLog_Versioned_v1-value`, `MetadataChangeProposal_v1-value`, `PlatformEvent_v1-value` 등 (DEV_OBSERVED).
- **subject versions**: `UNKNOWN` (구체적인 숫자 버전 확인 불가).
- **existing consumers**: `mce-consumer-job-client`, `generic-mae-consumer-job-client`, `datahub_doc_propagation_action` 등 (DEV_OBSERVED).
- **event_contract**: `MetadataChangeLog_Versioned_v1`는 영구(durable) 쓰기 후 발행되며, `entityUrn`, `entityType`, `changeType`, `aspectName`, `aspect`, `previousAspectValue`, `systemMetadata`, `previousSystemMetadata`, `created` (time, actor)를 포함함 ([mxe.md](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/what/mxe.md) 참조) (SOURCE_CONFIRMED).
- **consumer_conflict**: 독립 컨슈머 그룹 생성 시 경합 방지 가능 (DEV_OBSERVED).
- **DEV_MCL_INFRA**: `datahub-broker-1` (cp-kafka:7.9.2) 구동 중 (DEV_OBSERVED).
- **DEV_SCHEMA_REGISTRY**: 스키마 타입 `Avro` (DEV_OBSERVED). `used_for_dataset_history:NO`, `used_for_MCL_serialization:YES` (SOURCE_CONFIRMED/DEV_OBSERVED).

### DECISION_INPUT

| No | 비교 항목 (Criteria) | Timeline API | Kafka MCL |
| -- | ---------------- | ------------ | --------- |
| 1 | **TARGET endpoint** | 타겟 환경에서 활성화 및 접근 가능 (TARGET_USER_OBSERVED) | 타겟 환경 카프카 인프라 노출 및 접근 여부 확인 필요 (TARGET_RECHECK_REQUIRED) |
| 2 | **TARGET real history** | 최대 948 버전 인덱스 등 다수 이력 보존됨 (TARGET_USER_OBSERVED) | 타겟 환경 토픽 보존량 및 실제 메시지 확인 필요 (TARGET_RECHECK_REQUIRED) |
| 3 | **intermediate changes** | Retention에 의해 제거되었을 경우 중간 이력 유실 가능 | primary candidate; source emits after durable write, but exact downstream guarantee requires TARGET topic retention, consumer offset, payload decode, restart/catch-up and idempotency validation. |
| 4 | **TECHNICAL_SCHEMA** | 공식 스키마 정의됨 (ADD/MODIFY/REMOVE) ([timeline.graphql](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/datahub-graphql-core/src/main/resources/timeline.graphql) 참조) (SOURCE_CONFIRMED) | MCL 페이로드 구조상 지원됨 ([mxe.md](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/what/mxe.md) 참조) (SOURCE_CONFIRMED) |
| 5 | **DOCUMENTATION** | 공식 지원됨 ([timeline.graphql](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/datahub-graphql-core/src/main/resources/timeline.graphql) 참조) (SOURCE_CONFIRMED) | `editableSchemaMetadata`, `datasetProperties` 애스펙트 변동으로 지원됨 (SOURCE_CONFIRMED) |
| 6 | **TAG** | 공식 지원됨 ([timeline.graphql](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/datahub-graphql-core/src/main/resources/timeline.graphql) 참조) (SOURCE_CONFIRMED) | `globalTags` 애스펙트 변경으로 지원됨 (SOURCE_CONFIRMED) |
| 7 | **GLOSSARY_TERM** | 공식 지원됨 ([timeline.graphql](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/datahub-graphql-core/src/main/resources/timeline.graphql) 참조) (SOURCE_CONFIRMED) | `glossaryTerms` 애스펙트 변경으로 지원됨 (SOURCE_CONFIRMED) |
| 8 | **OWNERSHIP** | 공식 지원됨 ([timeline.graphql](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/datahub-graphql-core/src/main/resources/timeline.graphql) 참조) (SOURCE_CONFIRMED) | `ownership` 애스펙트 변경으로 지원됨 (SOURCE_CONFIRMED) |
| 9 | **actor/time** | 타겟 환경 실제 수신 여부 확인 필요 (TARGET_RECHECK_REQUIRED) | MCL `created` 필드를 통해 time, actor 방출 확인 ([mxe.md](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/what/mxe.md) 참조) (SOURCE_CONFIRMED) |
| 10| **retained-history dependency** | DB Retention 정책에 종속됨 (과거 데이터 정리 시 소실 위험) | Kafka Retention 정책에 종속됨 |
| 11| **outage catch-up** | 장기 장애 시 남아있는 DB Retention 이력까지만 복구 가능 | 오프셋 리셋을 통해 Kafka 토픽 Retention 내에서 복구 가능 |
| 12| **implementation complexity**| REST API 호출로 비교적 복잡도 낮음 | Kafka Consumer 및 Schema Registry 디코딩으로 복잡도 높음 |
| 13| **new runtime worker** | 주기적인 Cron/폴링 워커 필요 | T02 must inspect existing lifecycle/topology; no new container/service is approved. |
| 14| **initial backfill** | 과거 버전 적재(Index 기반)를 통한 전체 백필 유리 (Timeline) | 보존 기간 이전 과거 이력 백필 불가 |
| 15| **guaranteed forward** | 폴링 지연 및 누락에 취약함 | primary candidate; source emits after durable write, but exact downstream guarantee requires validation. |

- **Decision**: `MCL_PRIMARY_CANDIDATE` (Forward 캡처) 및 Timeline (Initial Backfill) 분리 설계 채택.

### RECOMMENDED_CAPTURE_ARCHITECTURE
- **initial_backfill**: Timeline API를 활용하여 기존에 저장된(retained) 메타데이터 이력을 초기 백필 처리함.
- **guaranteed_forward**: `MCL_PRIMARY_CANDIDATE`. Kafka MCL (`MetadataChangeLog_Versioned_v1`)을 구독. Source emits after durable write, but exact downstream guarantee requires TARGET topic retention, consumer offset, payload decode, restart/catch-up and idempotency validation.
- **nightly_reconciliation**: 매일 자정에 Timeline API와 MCL 누적 데이터를 비교 검증. Nightly reconciliation detects drift/deletion but does not synthesize missing intermediate events.
- **fallback**: 실시간 컨슈머 장애 시 Timeline API를 통한 주기적 폴링으로 임시 대체함 (Timeline fallback is best-effort, not exact).
- **rationale**: Timeline과 MCL 각각의 장점을 살린 분리 설계(Split Design)를 통해, 과거 이력 백필(Timeline)과 향후 캡처(MCL)를 분리. 타겟 환경 내 실제 MCL 접근성 및 정확성은 TARGET_RECHECK_REQUIRED 관문에서 재확인되어야 함.

### TARGET_RECHECK_REQUIRED
1. **MCL Topic 상태**: command: `kafka-topics --describe --topic MetadataChangeLog_Versioned_v1`, location: 타겟 카프카 환경, evidence: 존재 여부 및 파티션 수, PASS: 토픽 활성 상태.
2. **GMS Retention**: command: `env | grep ENTITY_SERVICE`, location: 타겟 GMS 컨테이너, evidence: `ENTITY_SERVICE_ENABLE_RETENTION` 설정값, PASS: 비즈니스 보존 정책 부합 여부 확인.
3. **MCL Schema 조회**: command: `curl -s http://<SR_HOST>/subjects/MetadataChangeLog_Versioned_v1-value/versions/latest`, location: 타겟 Schema Registry, evidence: Avro 스키마 JSON, PASS: 호환 스키마 여부 검증.
4. **실제 MCL 페이로드 검증**: command: `kafka-avro-console-consumer --bootstrap-server <BROKER> --topic MetadataChangeLog_Versioned_v1 --from-beginning --max-messages 1`, location: 타겟 툴링 환경, evidence: 디코딩된 JSON 메시지, PASS: 정상 디코딩 가능 및 이벤트 페이로드 확인.
5. **DB Retention 이력 확인**: command: `mysql -e "SELECT aspect, MAX(version) FROM metadata_aspect_v2 GROUP BY aspect;"`, location: 타겟 DB 환경, evidence: 저장된 최대 버전, PASS: 과거 이력 보존량 측정.
6. **Timeline API 조회 및 actor/time 재확인**: command: `curl -s <GMS>/timeline/v1`, location: API 접근 가능 네트워크, evidence: 200 OK 상태 및 actor/time 반환 여부, PASS: 정상 조회 가능.
7. **컨슈머 그룹 충돌 확인**: command: `kafka-consumer-groups --list`, location: 타겟 카프카 환경, evidence: 구동중인 그룹명, PASS: 신규 통합 컨슈머 그룹 이름 충돌 없음.

### T02_READY
- YES
- blocker: 타겟 MCL/Retention 상태 재확인 등 조건부 아키텍처 결정을 T02 단계에서 처리 가능함. (T04 배포는 해당 Gate가 해제되기 전까지 대기됨).

### NOT_EXECUTED
- 기존 MCL 페이로드 제한적 디코딩: 컨트롤러 취소 요청에 의해 이벤트를 반환받기 전 중단되었으며, 오프셋 커밋 없음 (NOT_EXECUTED_CONTROLLER_CANCELLATION).

### EXECUTED COMMANDS
- `docker ps`
- `docker exec datahub-datahub-gms-1 env | grep -i retention`
- `docker exec datahub-broker-1 kafka-topics --bootstrap-server localhost:9092 --describe --topic MetadataChangeLog_Versioned_v1`
- `docker exec datahub-broker-1 kafka-consumer-groups --bootstrap-server localhost:9092 --list`
- `curl -s http://localhost:18082/subjects`
- `curl -s http://localhost:18082/subjects/MetadataChangeLog_Versioned_v1-value/versions/latest`
- `docker exec datahub-broker-1 kafka-run-class kafka.tools.GetOffsetShell --broker-list localhost:9092 --topic MetadataChangeLog_Versioned_v1`
- `docker exec datahub-schema-registry-1 kafka-avro-console-consumer --bootstrap-server datahub-broker-1:9092 --topic MetadataChangeLog_Versioned_v1 --property schema.registry.url=http://localhost:8081 --from-beginning --max-messages 1` (Killed)
- `docker exec datahub-broker-1 kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group generic-mae-consumer-job-client`
- `docker exec datahub-mysql-1 sh -c 'mysql -u $MYSQL_USER -p$MYSQL_PASSWORD -D datahub -e "SELECT aspect, COUNT(*), MAX(version) FROM metadata_aspect_v2 WHERE aspect IN ('\''schemaMetadata'\'', '\''editableSchemaMetadata'\'', '\''datasetProperties'\'', '\''globalTags'\'', '\''glossaryTerms'\'', '\''ownership'\'') GROUP BY aspect;"'`
- `docker exec datahub-mysql-1 sh -c 'mysql -u $MYSQL_USER -p$MYSQL_PASSWORD -D datahub -e "SELECT MIN(createdon) FROM metadata_aspect_v2;"'`
