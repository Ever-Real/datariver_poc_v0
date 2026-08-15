# POC MCL 변경 이력 운영 Runbook

이 문서는 DataHub MCL을 DataRiver의 append-only 변경 원장으로 수집하는 표준 절차다. 현재 소스의
`createPocMclCapture(...).run()` bounded capture와 Node web 내부 일일 scheduler만 다룬다. Kafka offset
reset, DataRiver checkpoint reset, ledger 삭제, source identity의 환경 간 복사는 정상 운영 절차가 아니다.

현재 구현·DEV 실증 범위는 [POC Change Management 제품화 문서](../../docs/63_POC_CHANGE_MANAGEMENT_PRODUCTIZATION.md),
설계 결정은 [ADR-0123](../../docs/adr/0123-datahub-change-history-ledger.md)을 따른다. 실제 offset, credential,
IP, schema 본문은 이 문서나 Git evidence에 기록하지 않는다.

## 1. 배포 전 확인

- exact source SHA와 image의 `org.opencontainers.image.revision`이 일치해야 한다.
- `deploy/poc/Dockerfile.example` 또는 검증된 local Dockerfile에
  `poc-change-history-scheduler.mjs`와 `poc-mcl-capture.mjs` COPY가 모두 있어야 한다.
- `frontend/package.json`/lock의 `kafkajs`, `@kafkajs/confluent-schema-registry`,
  `kafkajs-snappy`, `snappyjs` pin을 함께 사용한다.
- `npm ci --ignore-scripts`와 Node 22 import가 성공해야 한다.
- 기존 `39080`을 유지한 side-by-side 검증은 candidate의 `POC_PORT=39081`로 수행한다.
- DataHub와 같은 Docker host/network라면 수동 `docker network connect` 대신 기존 overlay
  `deploy/poc/docker-compose.datahub-provider.yaml`을 함께 사용한다.

```bash
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml \
  -f deploy/poc/docker-compose.datahub-provider.yaml \
  config --quiet
```

DataHub 외부 network를 사용하지 않는 원격 DNS/TCP 배포에서는 base Compose만 사용한다. 새 proxy,
Kafka, Schema Registry 또는 sidecar를 만들지 않는다.

## 2. Kafka listener 계약

DataHub Docker 내부 서비스는 일반적으로 `broker:29092`, 외부 PREP/OPS client는
`DATAHUB_SERVER_IP_OR_DNS:9092`를 사용한다. 현재 DataHub의 `PLAINTEXT`/`PLAINTEXT_HOST` 구조를
유지하고 external advertised address만 client가 실제 도달 가능한 IP 또는 DNS로 둔다.

```text
KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:29092,PLAINTEXT_HOST://0.0.0.0:9092
KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://broker:29092,PLAINTEXT_HOST://DATAHUB_SERVER_IP_OR_DNS:9092
KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT
```

- `broker:29092`는 내부 listener로 유지한다.
- external advertised address에 `localhost`/`127.0.0.1`을 넣지 않는다.
- 보통 host에는 external `9092`만 publish한다.
- DataHub Kafka 설정 변경은 DataRiver application 배포와 별도 운영 변경이다.
- Kafka 주소는 제품 코드가 아니라 환경 설정이 소유한다.

## 3. Schema Registry 계약

다음 순서로 실제 contract를 발견한다. `MetadataChangeLog_Versioned_v1-value`는 흔한 이름일 뿐,
존재한다고 가정하지 않는다.

```bash
set -eu
SR_URL=http://DATAHUB_SCHEMA_REGISTRY_HOST:8081
root_file="$(mktemp)"
subjects_file="$(mktemp)"
latest_file="$(mktemp)"
trap 'rm -f "$root_file" "$subjects_file" "$latest_file"' EXIT

curl --fail-with-body --silent --show-error "$SR_URL/" >"$root_file"
curl --fail-with-body --silent --show-error "$SR_URL/subjects" >"$subjects_file"
python3 - "$subjects_file" <<'PY'
import json, sys
from pathlib import Path
values = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("\n".join(item for item in values if isinstance(item, str) and "MetadataChangeLog" in item))
PY

ACTUAL_SUBJECT=ACTUAL_METADATA_CHANGE_LOG_SUBJECT
curl --fail-with-body --silent --show-error \
  "$SR_URL/subjects/$ACTUAL_SUBJECT/versions/latest" >"$latest_file"
python3 - "$latest_file" <<'PY'
import hashlib, json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
schema = data.get("schema")
if not isinstance(schema, str):
    raise SystemExit("Registry schema is not a string")
print(json.dumps({
    "subject": data.get("subject"), "version": data.get("version"),
    "id": data.get("id"), "schemaType": data.get("schemaType", "AVRO"),
}, separators=(",", ":")))
print(hashlib.sha256(schema.encode("utf-8")).hexdigest())
PY
```

HTTP status/body가 JSON인지 확인하기 전에는 hash 명령을 실행하지 않는다. 증거에는 subject, subject
version, schema ID, schema type, SHA-256만 기록하고 전체 schema 본문은 저장하지 않는다.

## 4. Source identity

`POC_MCL_SOURCE_IDENTITY_HASH`는 DataHub 공식 identifier가 아니라 DataRiver의 환경별 운영 계약이다.
먼저 현재 환경 DB에서 provider/version/schema contract가 같은 source row를 찾고, 정확히 일치하면
그 환경 안에서만 재사용한다.
PREP에서 row가 없을 때 생성하는 descriptor contract 이름은 `PREP_TEST_SOURCE_IDENTITY_V1`이며,
OPS canonical identity로 자동 승격하지 않는다.

```bash
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml \
  exec -T pgvector sh -lc '
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT source_identity_hash, provider_name, provider_version,
       schema_contract_hash, created_at
FROM poc_change_history_sources
ORDER BY created_at, source_identity_hash;
"'
```

row가 없을 때만 실제 환경에서 발견한 값으로 아래 LF-terminated 여섯 줄의 UTF-8 SHA-256을 계산한다.
순서, 공백, 마지막 LF를 바꾸지 않는다.

```bash
set -eu
: "${POC_MCL_PROVIDER_VERSION:?actual provider version required}"
: "${ACTUAL_KAFKA_CLUSTER_ID:?actual cluster id required}"
: "${POC_MCL_KAFKA_TOPIC:?actual MCL topic required}"
: "${ACTUAL_SCHEMA_SUBJECT:?actual schema subject required}"
: "${POC_MCL_SCHEMA_CONTRACT_HASH:?actual schema hash required}"

{
  printf '%s\n' 'provider_name=DataHub'
  printf 'provider_version=%s\n' "$POC_MCL_PROVIDER_VERSION"
  printf 'kafka_cluster_id=%s\n' "$ACTUAL_KAFKA_CLUSTER_ID"
  printf 'topic=%s\n' "$POC_MCL_KAFKA_TOPIC"
  printf 'schema_subject=%s\n' "$ACTUAL_SCHEMA_SUBJECT"
  printf 'schema_contract_hash=%s\n' "$POC_MCL_SCHEMA_CONTRACT_HASH"
} | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
```

DEV, PREP, OPS는 각각 실제 provider tuple로 identity를 만든다. 다른 환경의 hash, first exact offset,
checkpoint를 복사하지 않는다.

## 5. DB 초기화와 기존 volume 갱신

새 PostgreSQL volume은 `docker-entrypoint-initdb.d/001-poc-state.sql`을 한 번 실행한다. 기존 volume에는
init hook이 재실행되지 않으므로 application update 전에 아래 idempotent SQL을 명시적으로 적용한다.

```bash
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml \
  exec -T pgvector sh -lc \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < deploy/poc/postgres-init/001-poc-state.sql
```

SQL은 `IF NOT EXISTS`, 이름 기반 constraint 교체, trigger 존재 검사를 사용한다. 적용 전 DB backup을
만들고, 적용 뒤 sources/ledger/checkpoints/link 네 table과 append-only trigger를 read-back한다.
checkpoint나 ledger를 초기화하는 rollback은 허용되지 않는다.

## 6. Phase A — 연결 확인

Scheduler는 아직 `false`로 둔다. candidate web container에서 다음을 확인한다.

1. `/healthz` 200 및 exact image revision
2. Kafka TCP와 `describeCluster()` 성공
3. advertised broker가 container에서 실제 도달 가능하며 loopback이 아님
4. `MetadataChangeLog_Versioned_v1` partition/high-low watermark 조회
5. Registry subjects/latest와 schema contract hash 일치
6. PostgreSQL의 네 change-history table
7. 등록된 active admin과 `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID` 일치
8. `GET /api/v1/change-history/access` 200

실패하면 network/listener/contract를 수정한다. 제품 코드에 주소를 하드코딩하거나 proxy/container로
우회하지 않는다.

```bash
# web container가 실제로 보는 advertised broker와 topic offset을 읽는다.
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml \
  -f deploy/poc/docker-compose.datahub-provider.yaml \
  exec -T web node --input-type=module - <<'NODE'
import { Kafka } from 'kafkajs'
const brokers = process.env.POC_MCL_KAFKA_BROKERS.split(',').map((value) => value.trim()).filter(Boolean)
const kafka = new Kafka({ clientId: process.env.POC_MCL_KAFKA_CLIENT_ID, brokers })
const admin = kafka.admin()
try {
  await admin.connect()
  process.stdout.write(`${JSON.stringify(await admin.describeCluster())}\n`)
  process.stdout.write(`${JSON.stringify(await admin.fetchTopicOffsets(process.env.POC_MCL_KAFKA_TOPIC))}\n`)
} finally {
  await admin.disconnect()
}
NODE

# 네 durable table과 private access endpoint를 확인한다.
docker compose --env-file deploy/poc/.env -f deploy/poc/docker-compose.poc.yaml \
  exec -T pgvector sh -lc "psql -v ON_ERROR_STOP=1 \
  -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" \
  -c \"SELECT to_regclass(name) AS relation FROM (VALUES
  ('poc_change_history_sources'),
  ('poc_change_history_ledger_events'),
  ('poc_change_history_checkpoints'),
  ('poc_change_history_cr_link_events')) AS required(name);\""
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:${POC_PORT:-39080}/api/v1/change-history/access >/dev/null
```

## 7. Phase B — exact boundary와 canonical bounded capture

metadata를 변경하기 전에 아래 runner를 web container 내부에서 실행한다. runner는 container가 이미
보유한 env만 읽고 credential을 출력하지 않는다.

```bash
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml \
  -f deploy/poc/docker-compose.datahub-provider.yaml \
  exec -T web node --input-type=module - <<'NODE'
import { createPocMclCapture } from './poc-mcl-capture.mjs'
import { createPocStateStore } from './poc-state-store.mjs'

const stateStore = createPocStateStore()
try {
  const result = await createPocMclCapture({ stateStore }).run()
  process.stdout.write(`${JSON.stringify(result)}\n`)
} finally {
  await stateStore.close()
}
NODE
```

source에 checkpoint가 없으면 첫 run의 partition별
`capturedHighWatermark = first_exact_offset = next_offset`이 exact guarantee boundary다. 기존 checkpoint가
있으면 `first_exact_offset`은 보존되고 `next_offset`부터 재개한다. DB ledger transaction 성공 뒤에만
checkpoint가 전진한다.

## 8. Phase C/D — 실제 event, replay, restart

승인된 isolated test asset에서 원래 없던 metadata를 ADD한 뒤 bounded capture하고, 동일 metadata를
REMOVE해 원복한 뒤 다시 capture한다.

- ADD와 REMOVE가 서로 다른 source offset에 각각 정확히 한 번 저장되어야 한다.
- actor/source time/category/aspect/operation을 확인한다.
- no-change rerun은 `processedRecords=0`, ledger count 불변이어야 한다.
- web restart 전후 `first_exact_offset` 불변, `next_offset` 비감소, duplicate position 0이어야 한다.
- DataHub 최종 current state는 원복하지만 append-only ledger는 삭제하지 않는다.

## 9. Phase E — Scheduler

직접 bounded capture와 replay가 성공한 뒤에만 다음을 설정하고 web만 recreate한다.

```text
POC_CHANGE_HISTORY_SCHEDULER_ENABLED=true
POC_CHANGE_HISTORY_SCHEDULER_TIME_ZONE=Asia/Seoul
```

startup은 현재 KST day boundary의 missed-run을 시도하고, PostgreSQL advisory lock 아래 capture 후 catalog
reconciliation 순서로 실행한다. durable receipt가 성공해야 같은 KST 날짜의 restart를 억제한다.
실패한 capture는 receipt/checkpoint를 성공 처리하지 않는다. 현재 제품에는 operator용 HTTP manual-trigger
endpoint가 없다. 실제 자정 timer를 관찰하지 않았으면 `DAILY_CLOCK_NOT_OBSERVED`로 기록한다.

## 10. Phase F — Monitoring과 CR

- Monitoring 기본 `데이터 변경현황`에서 schema/metadata/lifecycle event와 detail을 확인한다.
- 유효 PRIMARY link가 없는 transaction은 `미진행`이다.
- compatible CR에 PRIMARY를 연결해 미진행/weekly stage가 바뀌는지 확인한다.
- link는 CR state/round/revision/approval을 자동 변경하지 않는다.
- CLEAR PRIMARY 뒤 current primary는 없고 reverse history의 SET/CLEAR는 남아야 한다.
- viewer mutation은 403이며 subject/role/system client claim은 권한 근거가 아니다.

## 11. Troubleshooting

| 증상 | 원인/판정 | 처리 |
|---|---|---|
| `ECONNREFUSED 127.0.0.1:9092` | external advertised listener가 loopback | DataHub의 `PLAINTEXT_HOST` advertised address를 client-routable IP/DNS로 수정하고 별도 승인된 broker restart |
| scheduler/MCL `ERR_MODULE_NOT_FOUND` | local Dockerfile drift | 두 runtime `.mjs` COPY와 package/lock을 맞춘 뒤 image rebuild |
| Registry `JSONDecodeError`/404/401/403 | URL, subject, auth 또는 non-JSON response | `/subjects` HTTP response부터 재확인하고 schema hash 계산 중지 |
| `The server active subject is not configured` | active subject 누락/불일치 | access document의 등록된 active admin을 설정; 임의 ID 금지 |
| checkpoint가 low watermark보다 뒤 | Kafka retention gap | `HISTORY_GAP`/`BLOCKED_ENVIRONMENT`; offset/checkpoint reset 금지 |
| bounded capture timeout | network/listener/Registry/codec/malformed record/message bound | 실패 offset 앞에서 checkpoint를 멈추고 원인을 분리 진단 |
| `description is outside its string bound` | 구버전이 empty editable-field description을 거부 | empty-string normalization repair가 포함된 image로 재배포 후 durable checkpoint에서 replay; offset/ledger reset 금지 |
| scheduler disabled | `enabled=false` 또는 필수 MCL binding 누락 | direct capture 연결을 먼저 검증한 뒤 설정 상태 확인 |

## 12. 금지 및 증거 원칙

- raw MCL aspect/schema 본문, token, password, 실제 IP를 일반 로그/receipt에 저장하지 않는다.
- consumer group offset을 DB materialization 증거로 사용하지 않는다. PostgreSQL checkpoint가 권위다.
- provider timeout/partial page를 asset deletion으로 간주하지 않는다.
- live DEV PostgreSQL env를 상속한 unit test를 실행하지 않는다.
- deleted asset history와 CR link history를 cleanup하지 않는다.
- PREP/OPS 검증은 각 target에서 다시 수행하며 DEV PASS를 승격하지 않는다.
