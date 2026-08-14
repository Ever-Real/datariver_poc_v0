# DEV_INTEGRATION_CHECKPOINT_01 — POST-B01

## 판정

- 환경: `DEV_MAC_ARM64`
- 후보 제품 SHA: `138044ab8f819e3bc86d09a9d4d25d3d421b0141`
- `4deb4de..138044a` 제품 경로 diff: 없음 (`.orchestration/**` evidence만 존재)
- 판정: `BLOCKED`
- 이유: Search가 현재 PostgreSQL projection을 사용하지만 `DEGRADED_LAST_GOOD` 상태이며 관측시각이 `2026-08-13T20:22:24.886Z`로 stale이다. 실제 Catalog Detail은 DataHub HTTP 405를 받아 POC API 502로 실패한다. 이는 현 checkpoint의 current Search/Detail 최신성 조건을 충족하지 못한다.

## 실제 플랫폼

| 항목 | 결과 |
| --- | --- |
| POC web | 기존 `datariver-poc` Compose web만 port `39083`에 기동, `/healthz` 200 |
| 런타임 | 컨테이너 내 `node v22.19.0` |
| PostgreSQL / Redis / Neo4j | 기존 POC 컨테이너 모두 healthy |
| DataHub GMS / Kafka / Schema Registry | 기존 DEV 컨테이너 모두 healthy |
| 지원 리소스 | stop/delete/recreate 하지 않음; 기존 native `39080` 미변경 |
| 종료 / 재기동 | shutdown `620ms`, exit `0`, OOM `false`; healthy 재기동 `5607ms` |

따라서 실제 shutdown/restart는 10초 grace를 위반하지 않았고 `B-02` repair는 수행하지 않는다.

## Search / Catalog (T05, B-01)

- PostgreSQL current projection: 2,000 assets, `POSTGRES_CURRENT_PROJECTION`.
- Redis: POC inventory cache key 1개 확인, PostgreSQL/Redis health 정상.
- HTTP catalog initial response: `200`, `66ms`, 20 rows / 162,115 bytes.
- warm HTTP responses: `29ms`, `26ms`.
- 브라우저 관찰: 첫 Search 진입 `1.171s`, 검색 실행/결과 `0.690s`, warm 재진입 `3.088s` (체감상 더 느림, T08 performance debt).
- Resource Tree: oracle/postgres 합계 2,000을 표시. 첫 행 선택 시 Detail drawer는 보이나 provider 요청은 DataHub HTTP 405 → POC API 502 (`POC_PROVIDER_ERROR`).
- current projection meta: `DEGRADED_LAST_GOOD`; source generation `88c15c4274d4593717392085d963b6200452bf7c139428dddd8f3cfdad1d05b4`; stale/partial current state 해소는 `NOT_EXECUTED`.

## Change History / Scheduler (T04)

- ledger / checkpoint / CR-link table은 DEV PostgreSQL에 존재하나 rows는 각각 `0`이다.
- DEV local `.env`에 `POC_MCL_*`, scheduler enable, active-subject keys가 없다. 값은 읽거나 출력하지 않았다.
- MCL source / ledger / checkpoint / replay / dedup: `NOT_EXECUTED_CONFIGURATION_MISSING`.
- Scheduler는 실제 Node image에서 `enabled=false`, `disabledReason=DISABLED`, `Asia/Seoul` boundary `2026-08-14T15:00:00.000Z`, next `2026-08-15T15:00:00.000Z`를 계산했다.
- manual trigger, missed-run catch-up, duplicate suppression: `NOT_EXECUTED_CONFIGURATION_MISSING`.
- Kafka offset reset, event fixture 생성, DataHub metadata mutation은 하지 않았다.

## T06 권한 / CR 및 T07 UI

- 공식 `PUT /api/v1/change-history/access`으로 checkpoint 전용 최소 fixture를 설정했다: admin/steward/developer/viewer 4명, Oracle/PostgreSQL system 2개, assignment 2개. credential / 실제 사용자 정보는 사용하지 않았다.
- admin fixture에서 access/events/weekly API는 200이며 빈 ledger를 정직하게 0건으로 표시했다.
- browser supplied `X-Subject-Id`는 400 `PROTECTED_CLAIM`; stored active subject와 일치하지 않는 environment subject는 401로 거부됐다.
- 실제 ledger event가 없으므로 role별 assigned-system positive action, CR link/unlink, replay, reverse-history populated state는 `NOT_EXECUTED_NO_LEDGER_EVENT`이다. 임의 ledger/CR은 생성하지 않았다.
- 브라우저: Monitoring 기본 `데이터 변경현황` 탭은 fixture 후 200으로 source generation·0건·KST weekly·filter·empty state를 표시했다. Change Management weekly counters 7개는 0, 기존 CR 2개는 유지되며 CR detail의 `연결된 변경 이력` empty state가 표시됐다.
- fixture 전 UI의 `server active subject is not configured` alert은 환경 설정 부재를 정직하게 표시한 것이다.

## Fixture cleanup 경계

- pre-mutation 공식 evidence: access GET은 `ACCESS_NOT_CONFIGURED` 503, bootstrap의 `If-Match: "0"` 성공으로 access snapshot은 null/version 0이었다.
- 공식 access route는 GET/PUT만 제공하며 null/DELETE restore가 없다. PUT은 valid document only이다.
- pre-core full snapshot/hash는 mutation 전에 capture하지 않아 exact equality를 증명할 수 없다.
- 따라서 직접 SQL DELETE/UPDATE는 하지 않았다. checkpoint fixture는 DEV `poc_state`에 남아 있으며, cleanup은 별도 승인된 DB mutation Task가 필요하다 (`POLICY_CLEANUP_BLOCKER`).

## 차단 / 다음 조치

1. B-01 source repair를 추가 변경하지 않는다.
2. Catalog projection refresh가 `DEGRADED_LAST_GOOD`가 되는 원인 및 Detail의 DataHub 405는 별도 최소 repair Task로 분리한다.
3. Target/DEV MCL configuration contract와 approved fixture/cleanup 절차가 마련되기 전 exact capture runtime PASS를 주장하지 않는다.
4. `T08`, `T09`, G1-G4, push, PREP, OPS는 실행하지 않았다.
