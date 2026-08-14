# POST-CHECKPOINT-CURRENT-STATE

## 판정

- 기준 evidence SHA: `0bc06a3351f466b6d8e8674acec8798c6df5a487`
- 제품 candidate SHA: `138044ab8f819e3bc86d09a9d4d25d3d421b0141`
- B-01: `PASS_LOCAL_SOURCE`, 추가 repair 없음
- DEV_INTEGRATION_CHECKPOINT_01: `BLOCKED`
- B-02: `DEFERRED`, shutdown/restart 실패가 아니므로 repair하지 않음

## 추가 runtime 증거

Search/Catalog 읽기 전용 경로는 Node `v22.19.0`에서 `PASS_WITH_LIMITATIONS` 및 범위 한정
`RUNTIME_VERIFIED`다. 2,000 items, 검색, Tree, 유효 asset Detail 14/14 field,
`POSTGRES_CURRENT_PROJECTION`, `stale_at=null`을 확인했다. Redis 내부 사용 여부와 upstream
DataHub 호출 수는 이 표면에서 확인할 수 없다.

MCL/Scheduler는 `BLOCKED_RUNTIME`이다. MCL binding 0/9, scheduler disabled, Kafka protocol/admin
실패, ledger/checkpoint 0이며 metadata mutation·MCL decode·checkpoint advance·catch-up은
실행하지 않았다. T06/T07은 local validation PASS를 유지하지만 실제 event 기반 role scope,
CR link/unlink, weekly populated aggregate, reverse history는 dependency로 인해 실행하지 않았다.

Fixture 복구 후 active subject가 복구되었고, access API는 4-role/2-system HTTP 200, events는 HTTP
200 empty, `2026-08-10` KST weekly는 HTTP 200 empty로 독립 검증되었다. MCL required binding은
nonblank `0/9`, scheduler는 disabled이다.

보안 incident는 credential 값 없이 `local Orca terminal exposure=YES`, `external publication=NO`,
`rotation=NOT_EXECUTED`로만 기록한다. rotation은 별도 승인 대상이다.

## 핵심 증거

Node `v22.19.0` 컨테이너에서 web health와 PostgreSQL/Redis/Neo4j/DataHub/Kafka/Schema Registry를
확인했고 shutdown 620ms, restart 5607ms였다. Search HTTP는 66ms 초기, 29/26ms warm이지만
브라우저 warm 재진입은 3.088초였다. current projection은 PostgreSQL/Redis 2,000 asset을 사용했으나
`DEGRADED_LAST_GOOD` stale 상태다. Tree는 동작했지만 Detail은 DataHub 405에서 POC 502로 실패했다.

baseline `deploy/poc/.env`에는 MCL과 scheduler 관련 환경 설정이 없었다. checkpoint 후 active subject는
환경값과 저장된 fixture로 설정되어 access API 200 및 empty-state API/UI를 확인했지만, MCL과 scheduler는
실제 실행하지 않았다. T06은 최소 access fixture,
stored subject 권위, claim spoof 차단과 빈 API를 확인했으나 populated role/action/CR link를 실행하지
않았다. T07은 native monitoring/weekly/CR empty state를 확인했으나 populated event detail은
실행하지 않았다.

## 외부/정리 차단

- DataHub URL self-loop와 local `.env`/web 재기동 승인 필요
- Kafka advertised listener, MCL 환경키, post-checkpoint event fixture 승인 필요
- checkpoint access fixture cleanup은 공식 restore 경로가 없어 별도 DB mutation 승인 필요
- 기존 39080 및 외부 제공자/컨테이너는 중지·삭제하지 않음

## 다음

위 설정/승인 없이는 T08/T09를 시작하지 않는다. checkpoint 재실행이 PASS 또는 PASS_WITH_DEBT가
된 경우에만 T08 통합검증 후 T09 fresh audit로 이동한다. G1~G4는 모두 `NOT_APPROVED`이다.
