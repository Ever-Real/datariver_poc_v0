# ADR-0123: DataHub 변경 이력 원장과 현재 상태 조정

- Status: Accepted for candidate implementation — `T03_PERSISTENCE_READY`,
  `T04_DEV_CONDITIONAL_ON_T03_AND_LIFECYCLE_CONTROLS`,
  `TARGET_ACTIVATION_BLOCKED_TARGET_RECHECK`, `G1-G4 NOT_APPROVED`
- Date: 2026-08-13
- Owners: Architecture, Data Engineering, Security, Application
- Refines: ADR-0001, ADR-0002, ADR-0003, ADR-0007, ADR-0008, ADR-0010, ADR-0014,
  ADR-0027, ADR-0040, ADR-0090, ADR-0097, ADR-0109, ADR-0110

## Context

DataRiver는 DataHub의 현재 Catalog 상태를 읽고 PostgreSQL/pgvector에 재생성 가능한 현재
projection을 유지하지만, DataHub 메타데이터의 중간 변경을 장기간 조회할 수 있는 자체 원장은
아직 없다. DataHub는 적용된 Catalog 메타데이터의 canonical owner이고 DataRiver는 변경 의도,
승인, 감사와 로컬 read model의 owner라는 ADR-0002 경계는 그대로 유지한다. 따라서 변경 이력
기능은 DataHub 내부 DB를 읽거나 DataHub 원문을 복제하는 기능이 아니라, 승인된 provider 계약을
통해 관찰한 사건을 정규화하여 보존하는 DataRiver read/audit projection이다.

Timeline은 이미 보존된 과거 이력을 가져오기에 적합하지만 provider retention 이후의 중간 사건을
복원할 수 없다. Kafka Metadata Change Log(MCL)는 영속 쓰기 뒤 방출되는 forward capture 후보지만,
실제 타겟의 topic retention, partition/offset, Schema Registry 호환성, payload decode, 재시작과
catch-up이 검증되지 않았다. 두 소스 중 하나를 무조건 정확하다고 선언할 수 없으므로 과거와 향후
캡처를 분리하고, 정확성 범위와 타겟 활성화 관문을 명시해야 한다.

`PROJECT_HANDOFF_RECONCILIATION.md`에는 아직 통합되지 않은 ARCH-SEC-001 후보가 ADR-0122를
예약한다는 충돌 공지가 있다. 이 결정은 그 번호를 재사용하지 않고 ADR-0123을 사용한다.

## Evidence Scope

이 ADR의 주장은 다음 증거 등급으로 제한한다.

| 증거 | 관찰 또는 확인 결과 | 한계 |
|---|---|---|
| `TARGET_USER_OBSERVED` | TARGET DataHub `v1.6.0rc1`의 Timeline endpoint와 `TECHNICAL_SCHEMA`, `DOCUMENTATION` 이력이 관찰됨 | controller가 직접 재실행하거나 payload 원문을 검증한 증거가 아님 |
| `TARGET_USER_OBSERVED` | `TAG`, `GLOSSARY_TERM`, `OWNERSHIP`은 `NO_EVENT_OBSERVED` | `UNSUPPORTED`를 의미하지 않음 |
| `TARGET_USER_OBSERVED` | retained aspect history와 높은 version index가 관찰됨 | 타겟의 유효 최대 버전/시간 retention 정책은 `UNKNOWN` |
| `DEV_OBSERVED` | DEV DataHub `v1.6.0`의 MCL topic 한 partition, Schema Registry subject/schema와 기존 consumer가 관찰됨 | TARGET `v1.6.0rc1`의 schema/topic 호환성 또는 접근성을 증명하지 않음 |
| `DEV_OBSERVED` | 명시적 partition/offset에서 auto-commit 없이 기존 MCL 한 건을 bounded decode했고 기존 consumer offset은 전후 동일함 | 한 건의 capability 증거이며 모든 category/aspect 또는 연속 capture를 증명하지 않음 |
| `DEV_OBSERVED` | broker `cleanup.policy=delete`, 명목 retention 168시간, topic retention override 없음, 관찰 offset 범위 `[46325, 50423)` | segment 삭제는 비동기이고 TARGET의 유효 retention/복구 창 증거가 아님 |
| `DEV_OBSERVED_SOURCE` | native Node web 한 process에는 MCL loop, lock/lease/fence, signal drain과 supervised restart가 구현되지 않음 | 조건부 실행 위치 선택일 뿐 T04 준비 완료 증거가 아님 |
| `SOURCE_CONFIRMED` | DataHub `v1.6.0rc1` 소스가 Timeline 다섯 category와 durable write 이후 MCL 계약을 설명함 | ADR-0008의 production stable-version/digest gate를 대체하지 않음 |

검토한 공식 자료는 DataHub
[`timeline.graphql`](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/datahub-graphql-core/src/main/resources/timeline.graphql),
[`mxe.md`](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/what/mxe.md),
[`environment-vars.md`](https://github.com/datahub-project/datahub/blob/v1.6.0rc1/docs/deploy/environment-vars.md)이다.
최종 DEV 프로브는 `.orchestration/evidence/CHANGE-HIST-DEV-FINAL-PROBE.md`에 한정한다. DEV DataHub
`v1.6.0`의 decode와 retention 관찰을 TARGET DataHub `v1.6.0rc1` PASS로 변환하지 않는다. TARGET의
유효 retention, MCL topic, Schema Registry subject 호환성, 실제 payload decode와 재시작/catch-up은
모두 `TARGET_RECHECK_REQUIRED`이다.

## Decision

### 1. 조건부 소스 분리

다음 split design을 채택한다.

1. Timeline retained history는 초기 backfill의 source다. 허용된 다섯 category만 고정 typed
   adapter로 읽고, 초기 backfill은 항상 `BACKFILLED_BEST_EFFORT` precision으로 정규화한다.
2. MCL `MetadataChangeLog_Versioned_v1`은 forward capture의
   `MCL_PRIMARY_CANDIDATE`다. 타겟 관문을 통과한 MCL 사건은 DataRiver append-only ledger에
   정규화하여 `GUARANTEED_FORWARD` 범위를 형성한다. 관문 전에는 candidate일 뿐이며 exact나
   forward guarantee 표현을 API/UI/운영 증거에 사용하지 않는다.
3. Timeline fallback/polling에서 개별 사건의 identity, ordering, actor/time과 target retention
   연속성이 검증된 경우에만 `EXACT_TIMELINE`을 사용한다. 그 밖의 retained 사건은
   `BACKFILLED_BEST_EFFORT`이며 MCL gap이나 retention 손실로 사라진 중간 사건을 합성하거나 exact
   gap을 닫지 않는다.
4. 매일 조정은 current-state drift와 명시적/검증된 deletion만 찾는다. 최초 current snapshot은
   `INITIAL_BASELINE`, 이후 current-state 차이는 `DRIFT_DETECTED`이며 과거 중간 사건을 추정하지
   않는다.

precision은 `EXACT_TIMELINE`, `EXACT_MCL`, `DRIFT_DETECTED`, `BACKFILLED_BEST_EFFORT`,
`INITIAL_BASELINE`의 닫힌 enum이다. 다른 precision 문자열이나 암시적 exact 승격은 금지한다.
`EXACT_MCL`은 개별 사건의 source precision이고, `GUARANTEED_FORWARD`는 첫 성공 DB checkpoint부터
연속 검증된 범위를 가리키는 guarantee scope다. `GUARANTEED_FORWARD`를 precision enum에 추가하거나
Timeline backfill에 적용하지 않는다.

정규화 allowlist는 `TECHNICAL_SCHEMA → schemaMetadata`,
`DOCUMENTATION → datasetProperties/editableSchemaMetadata`, `TAG → globalTags`,
`GLOSSARY_TERM → glossaryTerms`, `OWNERSHIP → ownership`이다. provider version에서 aspect/category
mapping이 달라지거나 알 수 없는 aspect가 오면 그 payload를 일반 JSON으로 통과시키지 않고 해당
contract를 fail closed/recheck한다.

DataHub DB에 직접 연결하지 않는다. DataHub endpoint, Kafka/Schema Registry 자격증명과 network
identity는 deployment configuration/secret boundary가 소유하고 브라우저, 원장 row, 로그 또는
API 응답에 노출되지 않는다. 공식 소스에서 검토한 release candidate는 발견 증거이며 실제 배포는
ADR-0008의 expected/allowed version 계약과 별도 타겟 검증을 통과해야 한다.

### 2. backfill 경계와 첫 exact checkpoint

초기 활성화 시 controller는 소스 identity와 partition 집합을 고정하고 각 partition의 타겟
end offset `B[p]`를 한 번 읽어 `capture_boundary`로 기록한다. 이 읽기는 offset을 변경하지 않는다.
Timeline backfill은 provider가 boundary 관찰 시점까지 반환하는 retained history를 읽으며,
`B[p]` 이전의 시간 범위는 `BACKFILLED_BEST_EFFORT`다. provider가 시간/순서를 완전히 대응시키지 못하면
경계 주변 사건은 overlap 구간에서 두 소스로 재수집하고 deterministic dedup한다.

MCL은 각 partition의 `B[p]`부터 시작한다. 다음 조건을 모두 충족한 후에만 `B[p]`를
`first_exact_offset`으로 선언할 수 있다.

`B[p]` 기록 뒤 장시간 Timeline backfill보다 늦지 않게 MCL acquisition을 시작해야 한다. 실제
consume가 지연되더라도 `B[p]`가 topic retention 안에 계속 남았음을 입증해야 하며, 그 증거가
없으면 first exact checkpoint를 선언하지 않는다.

- 타겟 topic/partition과 retention이 승인된 장애/catch-up 창을 수용한다.
- 실제 타겟 Schema Registry schema와 payload를 decode한다.
- `B[p]`부터 연속 offset을 저장하고 DB checkpoint와 consumer restart를 검증한다.
- DB commit 전/후 장애, Kafka offset commit 손실과 replay에서 동일한 ledger 결과를 증명한다.
- 새 partition, schema incompatibility, offset gap을 건너뛰지 않고 fail closed한다.

첫 exact checkpoint 이전의 행은 사실에 따라 `BACKFILLED_BEST_EFFORT`, `INITIAL_BASELINE` 또는
`DRIFT_DETECTED`다. 조건을 통과한 이후의 연속 MCL 범위만 사건별 `EXACT_MCL`이다.
`ledger_guarantee_from`은 미리 읽은 `B[p]`나 consumer 시작 시각이 아니라, 모든 활성 partition의
초기 연속 transaction이 ledger와 DB `next_offset`에 처음 성공적으로 commit된 MCL checkpoint와
정확히 같은 경계다. 그 commit 전에는 null이고, 이후 gap 없이 검증된 범위만
`GUARANTEED_FORWARD`로 보고한다.
여기서 exact는 “검증된 source offset 범위의 사건이 적어도 한 번 전달되어 deterministic하게 한
번 materialize된다”는 의미다. provider 전체의 exactly-once delivery, DataHub 외부 writer와의 CAS,
retention 이전 과거 복원, 미검증 category 지원 또는 무중단 운영을 뜻하지 않는다.

### 3. overlap과 catch-up

backfill과 consumer는 같은 source identity를 사용한다. backfill 완료 후 controller는 Timeline
종료 관찰 시점과 MCL boundary 주변의 구성 가능한 overlap을 다시 읽고 dedup한다. overlap 길이는
타겟 관찰로 결정하며 portable source의 고정 business 값이 아니다. consumer가 lag를 따라잡아
연속 DB checkpoint가 현재 end offset에 도달한 뒤에만 initial run을 `NORMAL`로 바꾼다.

장애 복구는 PostgreSQL `next_offset`에서 시작한다. Kafka group offset은 진단/협조 값이고 DB
checkpoint가 materialization authority다. 운영자가 임의의 earliest/latest offset reset으로 gap을
숨길 수 없다. 필요한 offset이 topic retention에서 사라졌거나 partition topology가 바뀌면 해당
source/partition은 `HISTORY_GAP`과 `DEGRADED_GAP` 또는 `TARGET_RECHECK_REQUIRED`가 되고 exact
watermark는 마지막 연속 offset에서 멈춘다. Timeline retained history로 가능한 범위를
`BACKFILLED_BEST_EFFORT`로 복구할 수는 있지만, 찾지 못한 중간 사건을 합성하거나 gap을 exact로
닫지 않는다. 재시작은 DB checkpoint부터 overlap replay와 deterministic dedup을 수행하며 임의
Kafka offset reset이나 checkpoint 건너뛰기를 허용하지 않는다.

## Logical Model

아래는 T03가 구현할 논리 계약이다. 실제 migration/metadata 이름은 이 의미, 키, index와
append-only/RLS 불변식을 보존해야 하며 `docs/06_DATA_MODEL.md`와 생성 migration을 함께 갱신해야
한다.

| 논리 relation | 주요 필드/키 | 역할 |
|---|---|---|
| `change_history.sources` | Workspace, server-generated source ID, source identity SHA-256, provider/version/schema contract hash, active source generation pointer, capture state/version, `history_available_from`, `ledger_guarantee_from`, `first_exact_capture_at`, `first_timeline_checkpoint`, nullable `first_mcl_offset` vector, `last_successful_capture_at` | endpoint/credential 없이 외부 deployment identity, gate와 capture watermark 보존 |
| `change_history.capture_runs` | source, kind(`BACKFILL/CAPTURE/RECONCILIATION`), boundary document hash, state, precision, 시작/종료 UTC, `captured_at`, error code | backfill/catch-up/조정 실행 증거 |
| `change_history.checkpoints` | source/topic-contract/partition UQ, `first_exact_offset`, `first_mcl_offset` nullable, `next_offset`, last contiguous event/time, optimistic version | partition별 transactional DB checkpoint; MCL 적용 시에만 offset을 기록하며 감소/임의 reset 금지 |
| `change_history.source_events` | source-event ID, run, source kind, partition/offset nullable, Timeline fingerprint nullable, schema/payload SHA-256, `source_occurred_at` nullable, `detected_at`, `captured_at` | raw payload를 저장하지 않는 inbox/dedup evidence |
| `change_history.ledger_events` | semantic event ID, source-event/ordinal UQ, asset identity, category/aspect, normalized entity key, operation, before/after hash, bounded normalized delta, actor, `source_occurred_at` nullable, `detected_at`, `captured_at`, `effective_week_start` nullable, precision, tombstone flag | 무기한 append-only 정규화 원장과 주간 cohort 근거 |
| `change_history.generations` | source/generation ID, base checkpoint vector hash, state(`BUILDING/NORMAL/FAILED`), row counts/hash, created/completed UTC | current projection shadow generation과 atomic visibility |
| `change_history.current_facts` | generation, asset/category/entity-key UQ, current value hash/summary, latest ledger event, active/tombstone, observed UTC | 활성 generation의 현재 상태; history source가 아님 |
| `change_history.current_embeddings` | generation/asset UQ, source hash, bounded metadata, vector | 활성 최신 normal generation 검색용 pgvector projection |
| `change_history.assignee_policies` | Workspace/version UQ, role 순서, System scope/selection mode, effective interval, canonical hash/state | hard-code하지 않는 versioned attribution policy |
| `change_history.assignee_attributions` | event 또는 CR-transition basis, policy/System, nullable subject/responsibility, basis hash, observed UTC UQ | event/link와 weekly CR count의 immutable assignee snapshot |
| `change_history.cr_link_events` | link event ID, ledger event, CR/round, `CANDIDATE/PRIMARY` action, prior link hash, reason/policy/basis hash, actor/time | candidate/primary 변경의 append-only history |
| `change_history.idempotency_receipts` | Workspace/operation/key UQ, request hash, response hash/reference, expiry | CR link command의 exact replay |

필수 index는 다음과 같다.

- `source_events(source_id, topic_contract, partition, offset)`의 MCL partial unique index와
  `(source_id, timeline_fingerprint)`의 Timeline partial unique index
- `ledger_events(workspace_id, source_occurred_at DESC, event_id DESC)` keyset index
- `ledger_events(workspace_id, asset_id, source_occurred_at DESC, event_id DESC)` detail/history index
- category/precision/system/assignee 필터를 위한 Workspace 선두 bounded composite index
- `checkpoints(source_id, topic_contract, partition)` unique index
- `current_facts(generation_id, asset_id, category, entity_key)` unique index와 active/tombstone 조회
  index
- 한 ledger event의 current primary CR이 최대 하나가 되도록 append-only link projection에 대한
  deterministic uniqueness 또는 동등한 DB fence

모든 relation은 Workspace forced RLS를 적용한다. ledger/source/link evidence는 일반 runtime
role이 update/delete할 수 없다. checkpoint와 current projection의 제한된 update는 전용
server-owned 함수/role만 수행하며 감소, source identity 변경, 다른 Workspace 이동을 거부한다.

세 시각은 서로 대체하지 않는다. `source_occurred_at`은 provider가 보고한 발생 시각,
`detected_at`은 DataRiver가 처음 관찰한 시각, `captured_at`은 원장 transaction이 영속화된 시각이다.
`effective_week_start`는 정확한 `source_occurred_at`을 KST 주간 계약에 적용할 수 있을 때만 계산하고
그 밖에는 null로 두어 `time_unknown_count`로 분리한다. `history_available_from`은 현재 보존되어
권한상 조회 가능한 이력의 가장 이른 경계일 뿐 완전성 보장이 아니며, `ledger_guarantee_from`은
첫 성공적으로 commit된 MCL checkpoint와 동일한 검증된 연속 capture 경계다.
`first_exact_capture_at`은 그 checkpoint transaction의 실제 첫 exact 영속화 시각이고,
`first_timeline_checkpoint`는 최초 Timeline backfill checkpoint다.
`first_mcl_offset`은 MCL이 승인·적용된 source의 partition별 vector에만 존재한다.
`last_successful_capture_at`은
gap 없이 checkpoint를 전진시킨 마지막 성공 capture 시각이며 reconciliation 성공 시각과 섞지
않는다. 보장 근거가 없으면 guarantee/exact/MCL 필드는 null이고 추정값으로 채우지 않는다.

## Capture, Checkpoint and Dedup

MCL source-event identity는 canonical tuple
`(source_identity_hash, topic_contract, partition, offset)`의 SHA-256이다. 한 MCL message가 여러
schema field 변화로 정규화되면 semantic event identity는
`(source_event_id, normalized_category, normalized_entity_key, operation, deterministic_ordinal)`의
SHA-256이다. ordinal은 canonical sort 이후 부여되어 replay 순서와 무관하다.

Timeline source-event identity는 provider event identifier가 있으면 이를 포함하고, 없으면
`(source_identity_hash, asset_identity, category, occurred_at, actor_identity,
operation, normalized_delta_hash)`의 canonical SHA-256 fingerprint를 사용한다. 발생 시각이나 actor가
누락되면 해당 필드는 `UNKNOWN`으로 명시하고 precision은 `BACKFILLED_BEST_EFFORT`로 낮추며
`EXACT_TIMELINE`으로 승격하지 않는다.

consumer batch transaction은 다음을 원자적으로 수행한다.

1. singleton fence와 source/partition checkpoint를 lock하고 기대 `next_offset`을 확인한다.
2. raw Avro payload를 메모리에서 fixed schema로 decode하고 allowlisted category/aspect만
   정규화한다. 원문 aspect/schema document는 저장하거나 반환하지 않는다.
3. source-event inbox와 semantic ledger rows를 unique key로 insert하거나 exact replay로 확인한다.
4. 활성 current generation을 갱신하고 필요한 CR-link candidate를 별도 evidence로 기록한다.
5. 처리한 마지막 연속 offset 다음 값으로 DB `next_offset`을 전진시킨다.
6. DB commit 뒤 Kafka offset commit을 시도한다.

DB commit 전 실패하면 offset과 ledger가 함께 rollback된다. DB commit 후 Kafka commit이 실패하면
재전달되며 unique identity와 저장된 response가 같은 결과를 만든다. decode/schema/offset gap은 그
offset 앞에서 partition을 중지하고 checkpoint를 전진시키지 않는다.

## Current Projection

원장은 append-only이고 current projection은 재생성 가능하다. current API/search는 오직
`sources.active_generation_id`가 가리키는 `NORMAL` generation을 읽는다. schema change는
field path, type, nullable/description hash 등 필요한 bounded normalized fact/delta만 저장한다.
`schemaMetadata`, `editableSchemaMetadata` 또는 MCL의 raw before/after aspect document를 원장과
current table에 중복 보관하지 않는다.

명시적 MCL entity deletion 또는 ADR-0040의 검증된 완전 snapshot에서 확인된 부재만 asset
tombstone 권한을 가진다. 삭제된 asset은 current list/search와 latest vector generation에서
제외하지만 ledger와 CR link history는 무기한 남긴다. PIT/완전성 증거가 없으면
`DELETION_UNVERIFIED`를 기록하고 active current row를 삭제/tombstone하지 않는다.

nightly reconciliation은 shadow generation을 만든다. 시작 checkpoint vector를 고정하고 현재
provider state를 shadow에 적재한 뒤, 그 사이 ledger의 연속 MCL 사건을 shadow에 replay한다.
검증된 row count/hash, deletion gate와 종료 checkpoint가 모두 맞을 때 한 DB transaction에서
active generation pointer를 교체한다. 일부 page, vector 생성, provider 또는 DB 실패는 shadow를
`FAILED`로 남기고 직전 `NORMAL` generation을 계속 노출한다. 원장 capture는 조정 실패와 독립적으로
계속된다.

pgvector는 current projection의 최신 `NORMAL` generation만 검색 대상으로 한다. ledger event마다
embedding을 만들지 않으며 historical vector generation을 무기한 보존하지 않는다. 전환 중에는
직전 normal과 building generation 두 개까지 존재할 수 있고, 성공 후 직전 vector generation은
안전한 reader fence 뒤 제거할 수 있다. vector/Redis 장애는 ledger와 DB current detail의 정확성을
바꾸지 않는다.

## Scheduler and Timezone

새 container/service/process를 추가하지 않는다. 최종 DEV 프로브가 선택한 실행 위치는
`CONDITIONAL_EXISTING_WEB_PROCESS_CONTROLLER`다. DEV에는 native Node web 한 process가 있고 Compose
web replica는 없었지만, 현재 source에는 MCL loop, singleton lock/lease, signal drain과 supervised
native restart가 없다. 따라서 consumer를 HTTP server에 무조건 inline으로 넣거나 “현재 한
process”라는 관찰을 singleton 보장으로 사용하지 않는다.

T04 구현 전 기존 web-process lifecycle 안에 명시적이고 abortable한 background controller를 두고,
PostgreSQL advisory lock과 만료 가능한 durable lease/fence를 함께 구현해야 한다. 각 replica가 같은
controller를 시작해도 한 fenced owner만 capture/reconciliation과 checkpoint를 수행하고, stale
owner는 fence mismatch 뒤 DB transaction이나 checkpoint를 전진시키지 못해야 한다. consumer 오류는
HTTP process를 blind crash시키지 않도록 격리하며, signal 수신 시 fetch 중단, in-flight transaction
종결, checkpoint 전진 여부 확정, lease 해제/만료, HTTP/pool 종료 순서의 graceful shutdown과
restart/catch-up을 검증한다. 기존 Airflow는 다른 업무의 scheduler일 뿐 이 원장의 canonical
checkpoint가 아니다. 향후 process 분리가 필요하면 측정된 부하/격리 증거와 별도 ADR을 가진
`FOLLOW_UP`으로 처리한다.

현재 application package에 타겟 Kafka/Avro 계약을 만족하는 client/decoder가 이미 있는지는
`UNKNOWN`이다. 새 library 또는 lockfile 변경이 필요하면 검토된 버전/라이선스/오프라인 artifact,
checksum과 양 플랫폼 호환성 증거를 가진 별도 dependency `FOLLOW_UP`으로 처리한다. T02 결정과
T03 persistence가 dependency 설치/변경을 자동 승인하지 않는다.

조정 시각은 deployment configuration의 IANA timezone과 local wall-clock 값으로 노출한다. 이
기능의 승인된 business timezone은 `Asia/Seoul`, 초기 nightly 시각은 `00:00`이며 host timezone을
추론하거나 소스에 endpoint/환경별 값을 박아 넣지 않는다. 설정이 없거나 다른 timezone이면
자동 실행은 disabled/unavailable로 표시한다. 모든 DB 시각은 UTC로 저장하고 KST는 schedule과
presentation/weekly boundary에만 사용한다.

## Access, Assignee and Change Request Links

### 접근 경계

- Monitoring entry에는 기존 `operations.read`가 필요하고, 각 history row는 현재
  `catalog.read`, Workspace, classification, System/Domain/explicit-grant 정책을 다시 통과해야 한다.
- Change Management에서 history를 읽으려면 해당 CR의 `change.read`와 event asset의 현재
  `catalog.read`를 모두 만족해야 한다. 어느 한쪽 denial은 row와 count에서 제외된다.
- link command는 active human, 현재 `change.review`, 대상 CR `change.read`, event asset
  `catalog.read`와 아래 assignee policy의 System responsibility를 모두 요구한다. service identity,
  inactive/expired membership, stale target/System mapping은 거부한다.
- Global Admin의 Workspace-wide read capability는 자동 담당자 또는 자동 link 권한이 아니다.
  정책이 명시적으로 허용하고 현재 Canonical Admin evidence가 있을 때만 별도 role branch로
  평가한다.

기존 capability catalog와 System assignment에 다음 기본 노출을 구성한다. 이는 hard-coded role
bypass가 아니며 배포의 기존 configurable catalog/assignment 정책으로 관리한다.

| role | 변경현황 조회 | CR link/action | System 범위 |
|---|---|---|---|
| `admin` | 허용 | 허용 | 모든 System |
| `data_steward` | 허용 | 허용 | 현재 할당된 System만 |
| `developer` | 허용 | 허용 | 현재 할당된 System만 |
| `viewer` | 허용 | 금지(read-only) | 기존 read authorization 범위 |

POC open-policy는 그대로 유지한다. 위 기본 노출은 기존 `operations.read`, `catalog.read`,
`change.read`, `change.review`, Workspace, classification, System/Domain/explicit-grant와 active human
검사를 대체하거나 넓히지 않는다. 특히 steward/developer의 stale·expired·미할당 System과 viewer의
link/action은 fail closed하며, admin의 모든 System 범위도 행별 classification/Workspace 경계를
우회하지 않는다.

### 구성 가능한 담당자 정책

담당자 선택은 versioned policy로 관리한다. 기본 순서는 (1) routing System의 active/unexpired
`DATA_STEWARD` 중 existing policy-defined priority ordering의 최우선 후보, (2) 같은 조건의
`DEVELOPER` 중 같은 ordering의 최우선 후보, (3) DataHub Owner, (4) `UNASSIGNED`다. priority의
숫자 방향을 근거 없이 lowest/highest로 고정하지 않는다. 동일 단계에서는 적용 중인 policy의
priority ordering과 server-canonical subject identity로 deterministic하게 정렬하되 같은 최우선
순위가 정책상 해소되지 않으면 임의 선택하지 않는다.
DataHub Owner는 provider ownership에서 current authorized DataRiver human subject로 명확히 mapping된
경우에만 선택하며 provider 문자열, group 또는 미등록 identity는 권한/담당자 근거가 아니다.

policy는 이 기본 순서, routing System 범위, primary 선택 방식과 effective interval을 canonical
hash로 보존한다. server는 ADR-0109와 현재 CR target binding을 통해 routing System을 재해석하고,
`platform.system_assignees`의 active/unexpired human assignment와 priority를 사용한다. client가 role,
System, subject 또는 priority를 권한 근거로 제출할 수 없다.

해결 결과가 없거나 native/mapped System 충돌, 여러 동순위 후보 또는 policy 부재이면
`UNASSIGNED`로 남기고 임의 user/Admin을 대입하지 않는다. event/link 생성 시 선택된 subject,
responsibility, System, policy version/hash와 assignment basis를 snapshot한다. 이후 assignment 변경은
history를 다시 쓰지 않지만 현재 read/link authorization은 매번 재평가한다.

### CR primary/candidate history

한 history event는 여러 candidate CR과 최대 한 current primary CR을 가질 수 있다. server가
asset identity, routing System, 발생 시간과 CR round/target binding으로 candidate를 제안할 수
있지만 suggestion은 approval이나 primary link가 아니다. `SET_PRIMARY`, `ADD_CANDIDATE`,
`REMOVE_CANDIDATE`, `CLEAR_PRIMARY`는 reason, quoted version/ETag와 idempotency key를 가진 typed
command이며 모든 변경을 append-only link event로 남긴다. 잘못된 Workspace, 숨겨진 target,
current-round mismatch와 binding drift는 fail closed한다.

link는 CR의 state, round, approval, transition, requested content 또는 DataHub 적용 상태를 바꾸지
않는다. history event의 생성/연결/조정으로 CR이 자동 전이되거나 `COMPLETED/APPLIED`가 되지 않는다.
CR aggregate와 ADR-0110 revision history가 계속 canonical authority다.

## API and UI

API는 고정 typed adapter 결과만 제공하고 raw GraphQL/Avro/SQL/offset-reset 입력을 받지 않는다.
모든 list는 private/no-store keyset page이며 server가 authorization-pruned count를 계산한다.

| 계약 | 의미 |
|---|---|
| `GET /api/v1/change-history/summary` | 권한 범위의 category/precision/current health와 `source_occurred_at`, `detected_at`, `captured_at`, `effective_week_start`, `history_available_from`, `ledger_guarantee_from`, `first_exact_capture_at`, `first_timeline_checkpoint`, MCL 적용 시 nullable partition별 `first_mcl_offset`, `last_successful_capture_at` watermark 요약 |
| `GET /api/v1/change-history/events?...&cursor=&limit=` | 발생 시각/event ID keyset 순서의 bounded list; category, precision, System, assignee, CR link 필터 |
| `GET /api/v1/change-history/events/{event_id}` | bounded normalized diff, current/tombstone, source precision, assignee/link evidence의 정확한 detail |
| `GET /api/v1/change-history/weekly?week_start=` | 아래 exact KST week/stage 집계 |
| `GET /api/v1/change-history/events/{event_id}/cr-links` | primary/candidate와 append-only link history의 bounded page |
| `POST /api/v1/change-history/events/{event_id}/cr-link-events` | version/idempotency/reason fenced typed link command |
| `GET /api/v1/change-requests/{cr_id}/change-history` | 해당 CR과 event asset을 모두 읽을 수 있는 reverse link page |

`week_start`는 `Asia/Seoul` 기준 월요일 날짜여야 하고 구간은
`[월요일 00:00, 다음 월요일 00:00)`로 계산한 뒤 UTC predicate로 변환한다. 집계 단위는 CR이나
semantic row 수가 아니라 `normalized_change_transaction_id`의 distinct 값이다. 하나의 MCL
source-event 또는 하나의 Timeline canonical event에서 파생된 여러 category/entity row는 같은
transaction이고, 서로 다른 source event를 추정으로 합치지 않는다. 집계 cohort는 transaction의
canonical `source_occurred_at`이 주간 구간에 들어오는 사건이며, 시간 precision이 없어 구간을 확정할 수
없는 row는 weekly count에서 제외하고 `time_unknown_count`로 별도 보고한다.

stage는 집계 `as_of` 시점의 current primary CR 하나만 사용하며 아래 mapping은 presentation
전용이다. canonical CR state machine, transition, revision, approval 또는 target binding을 바꾸지
않는다.

| 표시 stage | canonical evidence |
|---|---|
| 접수 완료 | `REGISTERED`, 초기 `IN_REVIEW` |
| 재검토 | `CHANGES_REQUESTED`, 재제출 round의 `IN_REVIEW` |
| 변경 / TEST | `TESTING`, `APPLY_QUEUED`, `APPLYING`, `APPLY_FAILED` |
| 완료검토 | `FINAL_REVIEW` |
| 완료 | `APPLIED`, `COMPLETED` |

`total_count`는 권한 필터 뒤 해당 주의 distinct normalized change transaction 전체다.
`unlinked_count`는 진행 가능한 current primary CR이 없는 distinct transaction이다. primary가 없거나
candidate/non-primary link만 있는 transaction, 또는 current primary CR이 `REJECTED`/`CANCELLED`인
transaction은 모두 미진행으로 `unlinked_count`에만 포함하며 stage count에는 넣지 않는다.
각 `stage_count`는 나머지 transaction을 primary CR의 current presentation stage 하나에만 배정한
distinct count다. 따라서 정확히
`total_count = unlinked_count + received_count + recheck_count + testing_count +
final_review_count + completed_count`가 성립한다. candidate/non-primary link는 primary 선택이나
stage를 변경하지 않고, 동일 transaction의 여러 ledger row/assignee/System/CR history가 count를
증폭시키지 않는다. 결과는 `week_start`, `week_end_exclusive`, `timezone`, `as_of`, policy
version/hash, authorization watermark, `count_unit=DISTINCT_NORMALIZED_CHANGE_TRANSACTION`,
`total_count`, `unlinked_count`, 다섯 `stage_count`, `time_unknown_count`를 반환한다.

Monitoring에는 외부 dashboard 문서와 별개인 server-native `Change History` tab을 첫 번째로
추가하고 Monitoring 진입 시 항상 default active로 선택한다. 이 native tab은 관리자 구성에서
삭제, 재정렬 또는 URL 변경할 수 없고 외부 Dashboard Link 최대 여덟 개 제한에 포함되지 않는다.
기존 `platform.monitoring_configurations`의 외부 여덟 Dashboard Link, 순서, iframe/external fallback,
sandbox/no-referrer 계약은 그대로 유지하며 native tab은 provider URL을 fetch/proxy/frame하지 않는다.

native tab summary는 최소 `week_start`, `week_end_exclusive`, `timezone`, `as_of`, `capture_state`,
`precision_counts`(닫힌 다섯 precision 전부), `last_contiguous_checkpoint_at`, `active_generation`,
`last_reconciliation_state`, `last_reconciliation_at`, `total_count`, `unlinked_count`,
`received_count`, `recheck_count`, `testing_count`, `final_review_count`, `completed_count`,
`time_unknown_count`, `source_occurred_at`, `detected_at`, `captured_at`, `effective_week_start`,
`history_available_from`, `ledger_guarantee_from`, `first_exact_capture_at`,
`first_timeline_checkpoint`, MCL 적용 시 nullable partition별 `first_mcl_offset`,
`last_successful_capture_at`을
반환한다. UI는 요구 이름 그대로 `last successful sync`(`last_successful_capture_at`),
`source generation`(active source generation), `Schema Change`, `Metadata Change`,
`CR 미연결`(`unlinked_count`), `DataHub 상태`, `Sync 상태`(`capture_state`),
`history available from`(`history_available_from`), `ledger guarantee from`
(`ledger_guarantee_from`)을 표시한다. Change Management에는 같은 weekly contract의 table,
history badge/detail과 governed link action만 추가하며 기존 CR list/detail/state machine/revision/
approval/target binding을 보존한다.

## Failure Semantics

- MCL unavailable/decode/schema mismatch: 해당 partition checkpoint 앞에서 중지, exact watermark
  유지, gap을 Timeline으로 덮거나 skip하지 않음.
- PostgreSQL transaction 실패: ledger/current/checkpoint 모두 rollback, Kafka commit 없음.
- Kafka commit 응답 손실: DB checkpoint에서 replay하고 deterministic dedup; 중복 semantic row 없음.
- Timeline page/backfill 실패: run은 `PARTIAL/FAILED`, 이미 관찰한 행도 retained precision을 유지하며
  exact 또는 complete claim 없음.
- nightly provider/vector/page 실패: building generation만 실패하고 직전 normal generation 유지.
- Redis 실패/eviction: PostgreSQL에서 직접 읽고 결과 정확성/권한은 동일.
- deletion snapshot 불완전: tombstone 금지, `DELETION_UNVERIFIED` 노출.
- CR/assignee/policy drift: link command는 effect 0으로 실패하며 기존 link/CR history 불변.
- source identity, partition topology 또는 retention gap: `TARGET_RECHECK_REQUIRED`; arbitrary offset
  reset, silent source replacement과 exact watermark 전진 금지.

## Storage Estimate

ledger retention은 indefinite다. 이는 자동 삭제를 하지 않는다는 뜻이며 무한 storage를 보장한다는
뜻이 아니다. 실제 asset 수, 일일 사건 수, 평균 normalized delta/index 크기와 압축률은
`UNKNOWN`이고 타겟 측정이 capacity gate다. raw schema/aspect payload와 historical embedding을
저장하지 않아 중복을 제한한다.

계획 공식은 `연간 ledger bytes = 일일 semantic events × 365 × 평균 row+index bytes × headroom`이다.
`ESTIMATE_ONLY` 예로 10,000 events/day, 2 KiB/event, 1.3 headroom이면 약 9.1 GiB/year이며 실제
값은 표본 `pg_total_relation_size`와 index 크기로 교체해야 한다. 이 숫자는 승인된 business
capacity/retention 값이 아니다. current fact는 `asset × category/entity-key`에 비례하고 최신
pgvector raw vector 하한은 대략 `asset × dimension × 4 bytes`이며 metadata/index/WAL/backup은
별도다. DEV의 최신 catalog vector generation 2,000건 관찰은 TARGET 용량 증거가 아니다.

indefinite ledger 때문에 partition/drop/expiry 자동화는 승인하지 않는다. 월별 partitioning,
archive/WORM, 압축, 용량 alert와 backup/restore 값은 타겟 workload와 ADR-0010의 governed retention
결정 후 `FOLLOW_UP`이다. 저장공간 부족은 사건 삭제가 아니라 capture fail-closed/degraded와 운영
escalation을 유발해야 한다.

## Security

- fixed Timeline/MCL contracts만 허용하고 raw GraphQL, Avro, SQL, HTTP, topic 또는 offset command
  pass-through를 제공하지 않는다.
- MCL raw payload와 provider before/after document는 메모리에서 bounded decode 후 폐기한다. 원장에는
  normalized delta와 hash만 남긴다.
- source URL, topic endpoint, credential, Schema Registry credential, provider payload와 raw actor
  token은 브라우저/API/cache/log에 노출하지 않는다.
- cache key는 Workspace, subject permission scope, policy/classification version, source identity,
  active generation, request shape를 모두 포함한다. Redis는 optional TTL cache이고 권한/원장의
  source of truth가 아니다.
- list/count/detail/link는 같은 current authorization predicate와 forced RLS를 사용한다. 숨겨진
  asset/CR은 count, candidate와 cursor sequence에도 영향을 주지 않는다.
- source/event/link mutation은 bounded audit/outbox evidence를 남기고 high-cardinality URN, subject,
  payload 또는 offset을 telemetry label로 사용하지 않는다.

## Migration and Rollback

T03는 이 ADR 후보를 기준으로 SQLAlchemy metadata, deterministic Alembic migration, POC
PostgreSQL initialization이 해당되는 경로, repository/state adapter, `docs/06_DATA_MODEL.md`와 focused
tests를 함께 설계할 수 있다. schema는 expand-only로 먼저 배포하고 capture/schedule/UI는 기본
disabled로 둔다. T03 completion이나 source test는 T04 activation 권한이 아니다.

rollback은 controller/schedule과 UI capability를 끄고 마지막 normal current generation을 읽도록
한다. append-only ledger, checkpoint와 CR link evidence는 보존한다. evidence가 존재하면 downgrade가
이를 drop/truncate/update해서는 안 되며 안전한 downgrade가 불가능하다고 중지한다. current/vector
projection은 rebuildable하지만 source identity와 first exact checkpoint를 새 source에 재사용하거나
임의 reset하지 않는다.

## Validation

### T03 persistence

- metadata/migration/data-model deterministic agreement와 생성 migration diff
- unique dedup keys, append-only grants/triggers, forced RLS와 checkpoint monotonicity
- current active-generation pointer와 failed shadow invisibility
- idempotency/primary-link DB fence와 keyset indexes
- Ruff, strict mypy, focused pytest, `scripts/verify_static.py`

### T04 DEV capture — T03와 lifecycle controls 이후 조건부 진행

- DEV 구현은 T03 persistence와 advisory lock, durable lease/fence, abortable failure isolation,
  graceful shutdown controls가 먼저 완료되어야 함
- TARGET 활성화는 아래 `BLOCKED_TARGET_RECHECK` 관문을 통과하기 전까지 금지
- 타겟 topic 존재/partition/retention과 독립 consumer group 충돌 없음
- 타겟 Schema Registry exact subject/schema 호환성과 실제 MCL bounded payload decode
- boundary/first checkpoint, offset continuity, overlap, lag catch-up와 one-/multi-day outage 범위
- DB-before/after-commit, Kafka commit-loss, restart, duplicate delivery, schema/gap/partition-change
  negative tests
- no raw payload persistence/log/cache와 no arbitrary offset reset 증거

### T05-T07

- Timeline retained backfill와 MCL overlap deterministic dedup
- nightly current drift, explicit deletion, unverified deletion suppression, failed shadow generation
- KST midnight schedule, UTC storage, Monday-exclusive weekly boundary와 distinct count contract
- role/System/assignment/policy revocation negatives, hidden asset/CR count non-interference
- primary/candidate link history와 CR state/round/approval zero-effect regression
- summary/list/detail/weekly/link API bounds, Monitoring native view, 기존 외부 Monitoring tabs 회귀
- target dataset `EXPLAIN (ANALYZE, BUFFERS)`, storage sample, Redis unavailable, load/soak

T08/T09의 독립 검증/감사 전에는 production claim을 하지 않는다.

## Target Recheck Gate

T04의 TARGET 활성화는 다음 타겟 증거가 한 묶음으로 승인될 때까지
`BLOCKED_TARGET_RECHECK`다. T03 persistence와 필수 lifecycle controls 뒤의 DEV 구현 가능성은 이
TARGET 활성화 관문을 통과했다는 뜻이 아니다.

1. 실제 TARGET source identity와 approved DataHub version
2. MCL topic/partition inventory, effective retention과 earliest/end offset이 승인된
   outage/backfill/catch-up 창을 수용한다는 측정
3. Schema Registry subject/version 호환성과 auto-commit 없는 실제 TARGET MCL bounded decode
4. Timeline 대표 category의 실제 event 또는 명시적 `NO_EVENT_OBSERVED`, actor/time/ordering과
   retained-history 최대/시간 정책 재확인; unsupported 추론 금지
5. PostgreSQL advisory lock과 durable lease/fence를 통한 한 active owner, consumer group 충돌 없음,
   failure isolation과 graceful shutdown 증거
6. first successfully committed MCL checkpoint, restart/duplicate/lag/catch-up, DB/Kafka commit 경계와
   retention 초과 `HISTORY_GAP` fail-closed 증거

gate 실패 시 Timeline retained backfill/current reconciliation 후보만 남고 exact forward 기능은
활성화하지 않는다. DEV PASS를 TARGET PASS로 승격하지 않는다.

## Alternatives

### Timeline only

구현은 단순하지만 polling 사이 retention으로 제거된 중간 사건과 장애 중 변화를 정확히 복원할 수
없어 기각한다. retained backfill/fallback 용도로만 사용한다.

### MCL only

forward 후보로는 적합하지만 topic retention 이전의 과거 Timeline history를 복원하지 못해
기각한다. 또한 타겟 payload/restart 검증 전 exact claim을 만들 수 없다.

### DataHub DB 직접 조회/복제

provider 내부 schema와 credential에 결합되고 ADR-0002/0008 anti-corruption boundary를 우회하므로
금지한다.

### 새 Kafka consumer service/container 또는 새 database

현재 Single-node Pilot의 process/topology 요구와 승인 범위를 넓히므로 채택하지 않는다. 기존
process에서 singleton controller로 시작하고, 측정된 격리 필요가 생기면 별도 `FOLLOW_UP` ADR과
배포 승인을 요구한다.

### Redis 또는 pgvector를 canonical history store로 사용

eviction/재생성 가능한 projection을 영구 원장이나 checkpoint authority로 만들 수 없어 기각한다.

## Consequences

- T03 persistence 후보는 target MCL 없이 진행할 수 있지만 integration/release gate는 열리지 않는다.
- T04 DEV 구현은 T03와 필수 lifecycle controls 뒤에만 진행할 수 있고, TARGET 활성화는 타겟
  재검증 전 계속 차단된다.
- current read 성능과 append-only history 보존을 분리하고, deletion 후에도 이력/CR link를 유지한다.
- exact 범위가 checkpoint 이후로 제한되어 UI/API가 과거 retained history를 과장하지 않는다.
- 무기한 정규화 ledger는 자동 삭제 위험을 피하지만 workload 측정, backup/restore와 장기 capacity
  `FOLLOW_UP`을 필요로 한다.
- 기존 CR state/revision/approval/target binding과 Monitoring 외부 dashboard tabs는 변하지 않는다.
- `G1-G4`는 모두 `NOT_APPROVED`; merge, push, PREP, OPS, provider/runtime mutation 권한을 만들지
  않는다.

## NOT_EXECUTED

- product code, SQLAlchemy metadata, migration 또는 deployment configuration 변경
- product test, Ruff, mypy, pytest, `scripts/verify_static.py`, frontend build 또는 browser test
- DataHub/Timeline/MCL/Schema Registry payload 재조회 또는 provider runtime/data mutation
- container/service/process 생성, dependency 설치/변경, Redis/pgvector/PostgreSQL runtime mutation
- TARGET/PREP/OPS 실행, merge, push, G1-G4 승인
