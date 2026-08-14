# CURRENT.md — POST-B01 DEV 체크포인트

## 기준선

- repository: `/Volumes/SSD_Mac/workspace/datariver_poc_v0`
- coherent evidence SHA: `0bc06a3351f466b6d8e8674acec8798c6df5a487`
- coherent product candidate: `138044ab8f819e3bc86d09a9d4d25d3d421b0141`
- product diff `4deb4de..138044a`: 없음; `.orchestration/**` 증적만 추가됨
- environment: `DEV_MAC_ARM64`, Node `v22.19.0` container
- checkpoint: `BLOCKED`

## 실제 확인

- 플랫폼 health, PostgreSQL, Redis, Neo4j, DataHub, Kafka, Schema Registry가 확인되었다.
- shutdown `620ms`, exit `0`, OOM 없음; healthy restart `5607ms`였다. B-02는 수정하지 않는다.
- current projection은 2,000 assets와 PostgreSQL/Redis 경로를 보였지만 `DEGRADED_LAST_GOOD`이며 stale이다.
- Search HTTP는 초기 `66ms`, warm `29/26ms`였으나 브라우저 첫 진입 `1.171s`, warm 재진입 `3.088s`로 T08 성능 부채가 있다.
- Resource Tree는 표시되었으나 Catalog Detail은 DataHub 405 → POC 502로 실패했다.
- baseline `deploy/poc/.env`에는 MCL 환경키와 scheduler enable이 없었다. 다만 checkpoint 후 active subject는 환경값과 저장된 fixture로 설정되었고, access API 200 및 empty-state API/UI만 검증했다. MCL ledger·checkpoint·replay·dedup·manual trigger·catch-up은 실행하지 않았다.
- access fixture와 claim spoof 차단은 확인했지만 populated role action, CR link/unlink, reverse history는 실행하지 않았다.
- Monitoring native 탭, weekly 0건, CR empty state는 확인했지만 populated change detail은 실행하지 않았다.

추가 후속 runtime 증적에서 Search/Catalog는 Node 22에서 `PASS_WITH_LIMITATIONS` 및 해당 범위
`RUNTIME_VERIFIED`로 확인되었다. 2,000 items, 검색, Tree, 유효 asset Detail 14/14 field,
`POSTGRES_CURRENT_PROJECTION`, `stale_at=null`을 확인했다. Redis 내부 사용과 upstream DataHub
호출 수는 관측 증거가 부족하다. MCL/Scheduler는 `BLOCKED_RUNTIME`이다. MCL binding 0/9,
scheduler disabled, Kafka protocol/admin 실패, ledger/checkpoint 0이며 허용된 metadata mutation도
실행하지 않았다.

Fixture 복구 후 `39083` Node 22 web은 healthy이며 active subject가 복구되었다. access API는
4-role/2-system에 HTTP 200, events는 HTTP 200 empty, KST `2026-08-10` weekly도 HTTP 200 empty로
독립 검증되었다. 실제 event 기반 T06/T07은 여전히 `BLOCKED_DEPENDENCY`/`NOT_EXECUTED`다.

보안 상태: credential 값은 기록하지 않는다. local Orca terminal exposure는 `YES`, external
publication은 `NO`, rotation은 `NOT_EXECUTED`이며 rotation은 별도 승인이 필요하다.

## 상태·차단

- T03/T04/SCHEDULER/T05/T06/T07의 `IMPLEMENTED`, `VALIDATION_PASS`, `RUNTIME_VERIFIED`는 [PRIORITIES.md](.orchestration/dashboard/PRIORITIES.md)의 표대로 분리한다.
- T03 Python은 `NOT_RUNTIME_INTEGRATED`이다.
- T08/T09는 체크포인트 `BLOCKED`로 대기한다.
- DataHub self-loop URL/local `.env`와 web 재기동, Kafka advertised listener/MCL configuration, post-checkpoint event fixture는 별도 승인 대상이다.
- DEV access fixture는 DB에 남아 있으며 cleanup은 별도 DB mutation 승인 없이는 수행하지 않는다.
- PREP/OPS는 `UNKNOWN`/미실행이며 G1~G4는 모두 `NOT_APPROVED`이다.

## 금지·미실행

제품 추가 수정, B-02 repair, DB cleanup, DataHub/Kafka mutation, push, merge, PREP, OPS, T08, T09는 이 체크포인트에서 수행하지 않았다.
