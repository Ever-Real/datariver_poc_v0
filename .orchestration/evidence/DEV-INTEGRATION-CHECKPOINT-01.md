# DEV-INTEGRATION-CHECKPOINT-01 로컬 DEV 통합 체크포인트

## 판정

- 최종 판정: `BLOCKED`
- 역할: `50_QUALITY_VALIDATION + 20_PLATFORM_RELEASE` runtime verifier
- 검증 시각: `2026-08-14T04:17:30+09:00`
- runtime candidate SHA: `81b20b0404ef50c0c077bdeba32eced4f5976202`
- platform product SHA: `4857b70b1411a6ec78ad9397ee690c41fa59dc7d`
- platform product ancestry: `PASS` (`git merge-base --is-ancestor`)
- 환경: `DEV_MAC_ARM64`, macOS `26.5.2`, Node `v25.9.0`, npm `11.12.1`, Docker Compose `v5.3.1`
- 위험/권한: `LOW_RISK` 사전 승인과 이 task의 local DEV runtime 명시 승인만 사용
- 제품 repair, push, merge, publication, PREP, OPS: 모두 수행하지 않음
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

실행 시작 시 HEAD는 지정 SHA와 정확히 일치했고 작업트리는 clean이었다. 기존 39080 listener
PID `45143` 및 기존 DataHub/POC 지원 컨테이너는 중지, 삭제, 재생성하지 않았다. 후보는 사용하지
않던 loopback 39081/39082에만 띄웠다. `frontend/node_modules`가 없어 동일 lock임을 확인한 후 승인된
`dev-checkpoint-01-platform-validation/frontend/node_modules`를 symlink로 일시 재사용했고, 검증 후
symlink를 제거했다. dependency 설치나 lockfile 변경은 없었다.

## 빌드와 credentialless 후보 39081

| 항목 | 결과 | 관찰값 |
|---|---|---|
| `npm run build:poc` | `PASS` | 12.45초; 기존 500 kB chunk warning만 발생 |
| candidate | `PASS` | `POC_ENV_FILE=/dev/null`, `127.0.0.1:39081`, PID `46370` |
| `/healthz` | `PASS` | HTTP 200, 4.408 ms, 3 B |
| `/` | `PASS` | HTTP 200, 1.489 ms, 998 B |
| `/poc-api/capabilities` | `PASS` | HTTP 200, 2.843 ms; 7개 provider 모두 `disabled/NOT_CONFIGURED` |
| Catalog/Tree failure state | `PASS` | 각각 HTTP 503, 2.276/1.292 ms, `DataHub is not configured.` |
| unknown API / root POST | `PASS` | HTTP 404/405, 1.281/0.900 ms |

Control Plane에 PID와 URL을 포함한 `READY_FOR_VISUAL`을 전달했다. `VISUAL_DONE` 결과는 다음과 같다.

- Dashboard, Search, Monitoring, Change Management가 렌더링됐고 console warning/error는 없었다.
- header/menu와 작은 `[poc]` badge가 표시됐다.
- Search UI는 `projection v1 / POC_EMPTY_CATALOG_V1`의 0건 화면을 표시했으나 같은 후보의 direct
  Catalog/Tree API는 503이었다. 실패를 빈 성공처럼 보이게 할 수 있는 정직한 상태 표현 UX debt다.
- Monitoring은 external-tab empty state만 있었고 내장 데이터 변경현황은 없었다. Change Management에는
  기존 CR 상태 표만 있고 detected-change weekly/link UI는 없었다. 둘 다 T07 `NOT_STARTED` 범위다.

`VISUAL_DONE` 뒤 PID `46370`에만 SIGTERM을 보냈고 정상 종료 및 39081 해제를 확인했다. 39080 PID
`45143`은 계속 유지됐다.

## actual-provider 후보 39082

기존 local env `/Volumes/SSD_Mac/workspace/datariver_poc_v0/deploy/poc/.env`를 `POC_ENV_FILE`로만 지정하고
값을 출력하지 않았다. candidate는 `127.0.0.1:39082`, PID `47597`이었다.

### health와 capabilities

| 항목 | 결과 | 관찰값 |
|---|---|---|
| `/healthz` | `PASS` | HTTP 200, 3.107 ms |
| capabilities | `PARTIAL` | HTTP 200, 96.238 ms |
| DataHub | `available` | `LIVE`, probe 3 ms |
| Airflow | `available` | `AIRFLOW_API_V2`, probe 81 ms |
| LLM Chat / Embedding | `available` | 각각 15 ms |
| Neo4j | `available` | 91 ms |
| LLM Reranker | `unavailable` | `PROBE_FAILED`, 4 ms |
| MinIO / Grafana | `disabled` / `NOT_CONFIGURED` | local env에 구성되지 않음 |

### Catalog current projection

| 관찰 | 결과 |
|---|---|
| 첫 관찰 Catalog | HTTP 503, 15.274 ms, `PostgreSQL Catalog projection is warming` |
| 즉시 재요청 | HTTP 503, 2.127 ms |
| Search / Tree | HTTP 503, 2.700/2.851 ms |
| invalid search field | HTTP 400, 1.414 ms |
| 45초 bounded polling | 계속 HTTP 503 |
| candidate elapsed 6분 23초 후 | HTTP 503, 12.680 ms |
| PostgreSQL current projection | `catalog-inventory-v1:*` row `0` |
| Redis inventory cache | `datahub-inventory-v5:*` key `0` |

DataHub GMS의 candidate 실행 구간 slow-operation 로그에서는 고정 inventory GraphQL 요청이 최소 9회
완료됐고 각 완료 시간은 `25.529, 23.281, 18.315, 18.666, 25.521, 23.846, 18.535, 19.013,
24.914`초였다. 매 페이지에 `urn` sort criterion을 entity spec에서 찾지 못했다는 warning이 반복됐다.
6분 23초의 bounded 관찰 안에 atomic current projection은 한 번도 만들어지지 않았다.

따라서 warm Catalog, 정상 Search, Tree 및 실제 asset detail은 실행할 usable current asset set이 없었다.
actual provider의 `CURRENT`/정상 empty/provider failure 분리는 failure만 확인됐고 current 및 valid-zero는
입증하지 못했다. 이것은 경미한 UX debt가 아니라 체크포인트의 blocking 조건이다.

### 종료 경계

PID `47597`에 SIGTERM을 보냈을 때 39082 listener는 해제됐지만, 두 DataHub outbound connection을 가진
process가 약 71초 더 남았다. 첫 60초 drain 경계를 넘었으므로 별도 shutdown defect finding이다.
추가 bounded 관찰 11초 뒤 process가 자연 종료했고 승인된 candidate-only SIGKILL fallback은 사용하지
않았다. 최종적으로 PID `47597` 종료, 39081/39082 free, 기존 39080 PID `45143` 유지를 확인했다.

## 집중 fixture 검증

| 묶음 | 결과 | 포함 계약 |
|---|---|---|
| `node --test poc-mcl-capture.test.mjs` | `PASS`, 6/6, real 0.59초 | 실제 Confluent-framed Avro decode, bounded fan-out, multi-partition resume, durable checkpoint restart/dedup, malformed/DB failure no-advance, retention/topology/boundary fail-closed, payload/credential logging 부재 |
| `node --test poc-change-history-scheduler.test.mjs` | `PASS`, 4/4, real 0.26초 | disabled/missing no-op, KST startup catch-up와 completed duplicate skip, manual boundary, MCL→T05→receipt 순서, DST/IANA boundary |
| `node --test poc-state-store.test.mjs poc-server.test.mjs` | `PASS`, 26/26, real 1.71초 | scheduler singleton/receipt, ledger replay/checkpoint rollback/restart, access authority/CAS, admin·steward·developer·viewer, second-system ambiguity, header/body spoof, mapped/unmapped/stale zero-effect, link replay/conflict |

기존 fixture는 `ADD_CANDIDATE`와 `SET_PRIMARY` link를 검증하지만 `REMOVE_CANDIDATE`와 `CLEAR_PRIMARY`
unlink 명령의 명시적 성공 fixture는 포함하지 않았다. validator는 제품/테스트를 repair하지 않았으며 이
unlink 성공 경로는 `NOT_EXECUTED`로 남긴다.

## 기존 서비스 읽기 전용 확인

- PostgreSQL, Redis, DataHub GMS, Kafka broker, Schema Registry container는 검증 전후 모두 `healthy`였다.
- PostgreSQL `pg_isready`: accepting connections. Redis: `PONG`.
- DataHub `/config`: HTTP 200, 종료 후 1.812 ms. Schema Registry `/subjects`: HTTP 200, 24.037 ms.
- Kafka topic `MetadataChangeLog_Versioned_v1` partition 0 offset은 사전 `50904`, 사후 `50912`였다.
  동시에 동작하는 기존 DataHub 계층의 외부 drift `+8`이며, candidate에는 Kafka/MCL 설정과 Kafka socket이
  없었으므로 candidate 처리 증거로 귀속하지 않는다.
- Schema Registry에는 3개 subject가 있었고 `MetadataChangeLog_Versioned_v1-value`가 존재했다. latest는
  version 1, id 1, schema 8,987 B, contract SHA-256
  `d229d56f93936b990625d8f4a3d99750e59150438d29570705f1f1031670d7fe`였다.
- candidate가 호출한 provider 경로는 health/config와 고정 read GraphQL뿐이다. DataHub metadata write,
  Kafka topic/offset write, arbitrary DB row mutation은 실행하지 않았다.

## actual MCL ledger/checkpoint/catch-up

읽기 전용 transaction에서 `poc_change_history_sources`, `poc_change_history_ledger_events`,
`poc_change_history_checkpoints`, `poc_change_history_cr_link_events`가 모두 0 row임을 확인했다.
local env에는 active subject와 MCL broker/client/group/topic/source/schema/provider/SR binding이 없고 scheduler는
비활성화돼 있었다. 안전한 기존 fixture도 없었다. 실제 catch-up은 설정을 발명하고 ledger/checkpoint 또는
Kafka consumer 상태를 쓰지 않고는 실행할 수 없으므로 `NOT_EXECUTED`다. 빈 ledger를 PASS나 catch-up
성공으로 가장하지 않는다.

## blocking findings, debt와 미실행 범위

### Blocking

1. `B-01`: usable Catalog current projection이 6분 23초 bounded window 안에 생성되지 않았다. Catalog,
   Search, Tree는 계속 503이었고 warm/detail/current/valid-zero 계약을 검증할 수 없다.
2. `B-02`: SIGTERM 후 listener는 닫혔지만 background provider fetch 때문에 process drain이 약 71초
   걸렸다. 강제 종료 없이 끝났지만 task-local 정상 종료 경계의 defect다.

### Debt

- credentialless Search UI의 0건 표현과 direct API 503의 의미 불일치
- actual capability의 Reranker `unavailable`
- T07 내장 데이터 변경현황 및 weekly/link UI `NOT_STARTED`
- 명시적 unlink 성공 fixture 부재

### NOT_EXECUTED

- actual current/warm Catalog, 정상 Search/Tree/detail 및 valid-zero 분리
- actual MCL ledger append/checkpoint/catch-up/scheduler 실행
- DataHub metadata write, Kafka topic/offset write, provider mutation, arbitrary DB data mutation
- cache flush, 기존 PID/container/service/network/volume lifecycle
- Linux/amd64, PREP, OPS, TARGET, load/soak, production gate
- 제품/test/config repair, push, merge, publication, G1-G4 승인

## 결론

빌드, credentialless API/visual, T04/Scheduler/T06 fixture와 기존 의존성의 읽기 전용 health는 통과했다.
그러나 actual-provider 후보가 bounded 6분 23초 안에 PostgreSQL current projection을 만들지 못해 핵심
Catalog/Search 계약을 사용할 수 없었다. shutdown drain defect도 별도로 관찰됐다. 따라서 exact runtime
candidate `81b20b0`의 local DEV integration checkpoint는 `BLOCKED`이며 release/PREP/OPS 승인이 아니다.
