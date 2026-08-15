# DEV-FULL-T03B MCL 런타임 연속 검증

- 작업 시각(UTC): `2026-08-15T11:40:08Z`
- 작업 트리: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-full-mcl-runtime`
- 시작 HEAD: `5ac7d1007a7ec9ac75baab29a7897a6791d3182a`
- 마지막 제품 SHA: `7bc27171fe91fd0e886aa55e986e18d9f3749ebc`
- 제품 소스 변경: 없음
- 실제 DEV source identity: `a2a280e5d04cb3ded4f0a36c6fa7b30216eb20ee30be4f5133bba5d0c1154e34`
- 토픽/partition: `MetadataChangeLog_Versioned_v1` / `0`

## 결론

T03에서 이미 통과한 태그·용어·소유권·설명·컬럼·table/view lifecycle mutation은 반복하지 않았다.
중단 지점 이후의 table rename 정책, 무변경 replay, scheduler 순서/동일 일자 억제, PostgreSQL
current projection 및 Search/Tree 격리를 실제 DEV에서 확인했다. `table_v1` 삭제와 `table_v2`
신규 schema는 별도 lifecycle/schema event로만 기록되었고 `RENAME`은 합성되지 않았다.

다만 live Embedding provider는 `fetch failed` 상태여서 실제 current generation은 생성되지 않았다.
또한 검증 과정에서 Node 22 컨테이너에 live PostgreSQL 환경을 상속한 채 state-store 테스트를 한 번
실행하여, 테스트의 첫 generic `core` write가 실제 `poc_state.core`를 version `24`로 갱신하는 사고가
발생했다. 이전 core JSON의 검증 가능한 복구 원본이 없어 추측 복구나 reset을 수행하지 않았다.
MCL source/checkpoint/ledger와 access row는 이 사고로 변경되지 않았다.

## Table rename 정책과 append-only 결과

재개 직전 DB 확인에서 안내된 `next_offset=52925/version=77`보다 한 건 앞선 상태가 발견됐다.
`next_offset=52926/version=78`이며 offset `52925`의 `table_v1 status DELETE`가 이미 존재했다.
따라서 해당 mutation은 반복하지 않고 다음 미실행 단계부터 재개했다.

| 단계 | 실제 MCL/ledger 결과 |
|---|---|
| old `table_v1` remove | offset `52925`, `LIFECYCLE/status/DELETE` |
| new `table_v2` valid schema | offset `52935`, `TECHNICAL_SCHEMA/schemaMetadata/CREATE`, `field:id` |
| old `table_v1` reactivate | offset `52939`, `LIFECYCLE/status/CREATE` |
| new `table_v2` false baseline | offset `52940` source record 처리, semantic ledger `+0` |
| new `table_v2` remove | offset `52941`, `LIFECYCLE/status/DELETE` |

첫 재개 capture는 공유 DEV 토픽의 그 사이 레코드를 포함해 `52926→52939`의 13개 source record를
처리했지만 fixture semantic ledger에는 `table_v2 schema CREATE` 한 건만 추가했다. 전체 fixture
ledger는 `30→33`, checkpoint는 최종 `first_exact=52849`, `next_offset=52942`, `version=94`다.
old/new URN의 결과에는 `RENAME` operation이 없으며 제품의 closed operation vocabulary도 이를
허용하지 않는다.

## Canonical capture replay

사용한 비밀 비포함 canonical runner 형식은 다음과 같다. 컨테이너 보유 PostgreSQL/DataHub 자격
정보는 출력하거나 CLI 인자로 전달하지 않았다.

```text
docker exec -i -w /app \
  -e POC_MCL_KAFKA_CLIENT_ID=datariver-poc-mcl-runtime \
  -e POC_MCL_KAFKA_GROUP_ID=datariver-poc-mcl-runtime \
  -e POC_MCL_KAFKA_TOPIC=MetadataChangeLog_Versioned_v1 \
  -e POC_MCL_SOURCE_IDENTITY_HASH=a2a280e5d04cb3ded4f0a36c6fa7b30216eb20ee30be4f5133bba5d0c1154e34 \
  -e POC_MCL_SCHEMA_CONTRACT_HASH=09bd3b6105103832a287a1e8af3c563054164ec36c5886e7bbcb95561c8b987b \
  -e POC_MCL_PROVIDER_NAME=DataHub \
  -e POC_MCL_PROVIDER_VERSION=v1.6.0 \
  datariver-poc-web-1 node --input-type=module - < run_capture_v4.mjs
```

무변경 replay 결과는 `processedRecords=0`, `ledgerEvents=0`이다. replay 전후 ledger `33`,
checkpoint `52849/52942/version 94`가 모두 동일했다.

## Scheduler runtime

기본 lock의 KST 당일 receipt가 이미 존재하여 full ordered path가 억제되는 상태였다. 기존 receipt를
수정하지 않고 DEV 전용 lock `datariver:poc:change-history-scheduler:v1:dev-full-t03b`를 사용해 web만
재생성했다. startup은 capture 후 DataHub reconciliation을 완료하고 다음 receipt/current projection을
durable PostgreSQL에 기록했다.

- receipt: version `1`, boundary `2026-08-14T15:00:00.000Z`, trigger `scheduled`, completed
  `2026-08-15T11:26:18.596Z`
- current projection scope: `catalog-inventory-v1:930cf230a739a70c`
- projection: version `2`, items `2002`, generation
  `291454153495da07c3d93750e0885b0ea25a1be0c58e79044f863cf9dcf22710`
- 같은 설정으로 web을 다시 재생성한 뒤 receipt version `1`, projection version `2`, ledger `33`,
  checkpoint `52942/version 94`가 불변이었다.
- 검증 종료 전에 scheduler lock을 canonical
  `datariver:poc:change-history-scheduler:v1`로 복원했다. web은 Node `v22.19.0`, host port `39083`,
  health `healthy`다.
- 실제 자정 시계 경과는 `DAILY_CLOCK_NOT_OBSERVED`다.

## Current/history 격리

PostgreSQL current projection과 live API(`39083`) 결과는 일치했다.

| 표면 | `table_v1` | `view_v1` | `table_v2` |
|---|---:|---:|---:|
| PostgreSQL current projection exact count | 1 | 1 | 0 |
| Catalog exact search total | 1 | 1 | 0 |
| Schema Tree | 포함 | 포함 | 미포함 |
| append-only ledger | 유지 | 유지 | schema CREATE + lifecycle DELETE 유지 |

Embedding runtime은 `/poc-api/datahub/vector-index`에서 `configured=true`, `state=FAILED`,
`generation=null`, `indexed=null`, `last_error=fetch failed`였다. PostgreSQL에도 위 current projection
generation의 embedding row는 `0`건이었다. 따라서 live vector current-generation 검증은
`BLOCKED_PROVIDER_UNAVAILABLE`이며 PASS로 과장하지 않는다. current-SHA negative fixture는 provider
partial/failure에서 PostgreSQL last-good을 보존하고, 삭제/재활성화 URN을 Search/Tree/Chat exact/vector
generation에서 격리하는 계약을 통과했다.

## 집중 검증

Node 22.19.0의 기존 web 컨테이너에서 테스트 입력만 stdin으로 전달했다. 실제 provider/DB 환경은
빈 값으로 명시해 테스트 double/memory 경계를 사용했다.

| 검증 | 결과 |
|---|---|
| `poc-mcl-capture.test.mjs` | PASS `14/14` |
| `poc-change-history-scheduler.test.mjs` | PASS `4/4` |
| `poc-server.test.mjs` | PASS `14/14` |
| `poc-catalog-performance.test.mjs` | PASS `5/5` |
| `poc-state-store.test.mjs` runtime/double cases | PASS `11/11` |
| state-store/init SQL exact parity | PASS, 15 contracts, upgrade order, no `pg_get_constraintdef` |
| `git diff --check` | PASS |
| 제품 diff | 없음 |

호스트 Node `25.9.0` 병렬 시도는 지원 runtime이 아니어서 중단했다. Node 22 재실행 결과만 acceptance
evidence로 사용한다. 제품 diff가 없고 runtime image는 이미 Node 22 build이므로 별도 lint/build 재실행은
하지 않았다.

## Runtime incident / 남은 blocker

- 잘못 격리된 첫 state-store 테스트 명령이 live PostgreSQL의 `core`를 한 번 썼다.
- 관측 결과: `core.version=24`, `sequence=11`, `changeRecords=1`, 첫 ID `request-from-core`.
  access-protected 필드(`adminMemberships`, `adminSystems`, `adminSystemAssignees`,
  `adminSystemSchemaScopes`)는 fence에 의해 보존됐다.
- `change-history-access-v1`은 version `1`, active subject `checkpoint-admin`, users `4`, assignments `2`로
  변경되지 않았다.
- MCL checkpoint `52942/version 94`, ledger `33`은 사고 전후 불변이다.
- 검증된 이전 core JSON이 없어 복구는 `NOT_ATTEMPTED_NO_VERIFIED_PRIOR_VALUE`다. 이 blocker는
  core의 권위 있는 이전 snapshot을 확보한 뒤 별도 통제 작업으로 복구해야 한다.

