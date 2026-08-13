# CHANGE-HIST DEV 최종 프로브

## 범위와 기준선

- Task: `CHANGE-HIST-T02A-DEV-FINAL-PROBE`
- 문서 기준 SHA: `57c43cf5921bc55a5e2a5d02ec00310943d25320`
- 환경: `DEV_MAC_ARM64`
- DataHub runtime: image tag 기준 `v1.6.0` (`DEV_OBSERVED`)
- TARGET DataHub `v1.6.0rc1`과 TARGET의 사용자 관찰은 이 문서의 DEV 결과와 동일시하지 않는다.
- 시작 상태: Task worktree의 HEAD가 기준 SHA와 일치했고 `git status --short`가 비어 있었다.
- 이 프로브는 Kafka, DataHub, container, process를 읽기만 했다. credential 값과 원문 aspect 문서는
  읽기 결과로 출력하거나 파일에 기록하지 않았다.

## MCL bounded decode

### 토픽과 스키마

- topic: `MetadataChangeLog_Versioned_v1` (`DEV_OBSERVED`)
- partition: `0` 한 개, replication factor `1` (`DEV_OBSERVED`)
- Schema Registry subject: `MetadataChangeLog_Versioned_v1-value`, version `1`, schema id `1`
  (`DEV_OBSERVED`)
- 관찰한 top-level field는 `entityType`, `entityUrn`, `changeType`, `aspectName`, `aspect`,
  `systemMetadata`, `previousAspectValue`, `previousSystemMetadata`, `created` 등을 포함했다.

### 명시적 offset 샘플

`partition=0`, `offset=50422`, `max-messages=1`, `enable.auto.commit=false`로 읽고, stdout을 즉시
field-limited sanitizer로 전달했다. entity URN은 SHA-256으로 치환했고 aspect 원문은 메모리에서
크기와 SHA-256만 계산한 뒤 폐기했다.

| field | sanitized observation |
|---|---|
| entityUrn | `sha256:f6b964d9a5f97294399019a53b782285ec6268a6f056c23379c430991db53c85` |
| entityType | `dataHubExecutionRequest` |
| aspectName | `dataHubExecutionRequestResult` |
| changeType | `UPSERT` |
| aspect | present, object, 18,768 bytes, `sha256:720778e4d2d9ea48e6d21177efae84d31d6d7eb8c96438d429bf7e16412294f7` |
| previousAspectValue | present, object, 12,184 bytes, `sha256:d1e1a118af486ed565a5a8c7e20104ba3181eb7a88ee7b8709ad1d2ed0b0aab4` |
| systemMetadata | present, object, 600 bytes, `sha256:59c1a90a9bc6d17909a6876be683e30c61f40ce80185e6d43182a762c7bdc292` |
| previousSystemMetadata | present, object, 513 bytes, `sha256:91b8128061d311823281a8d3e81a84241c4b0dabffbbbff1a5d628236cad456b` |
| created.time | `1786613441792` / `2026-08-13T09:30:41.792Z` |
| created.actor | `urn:li:corpuser:__datahub_system` |

이 한 건은 DEV에서 Avro decode와 요구 field 관찰이 가능하다는 capability 증거다. 모든 entity,
aspect, change type 또는 TARGET payload를 대표하거나 end-to-end exact capture를 증명하지 않는다.

### offset 비변경 증거

기존 `generic-mae-consumer-job-client`의 versioned MCL 상태는 bounded decode 직전과 직후 모두
`CURRENT-OFFSET=50423`, `LOG-END-OFFSET=50423`, `LAG=0`이었다 (`DEV_OBSERVED`). 별도 group id를
지정하거나 생성하지 않았고 auto commit을 비활성화했다. topic/group/offset 변경은 실행하지 않았다.

처음 두 시도는 container 내부에서 broker의 host listener인 `localhost:9092`를 사용해 각각 15초와
60초 안에 메시지를 받지 못했다. broker metadata가 공개한 DEV 내부 listener `broker:29092`를 사용한
세 번째 bounded 시도만 성공했다. 실패한 시도도 auto commit이 꺼져 있었고 기존 group offset은
변하지 않았다.

## Kafka retention과 복구 창

### 유효 설정

| 항목 | DEV 관찰값 | 해석 |
|---|---:|---|
| broker `log.cleanup.policy` | `delete` | compact가 아닌 시간/segment 삭제 정책 |
| broker `log.retention.hours` | `168` | 명목상 7일 보존 기본값 |
| broker `log.retention.ms` / `minutes` | unset | `hours=168`이 적용됨 |
| broker `log.retention.bytes` | `-1` | broker byte cap 없음 |
| broker `log.segment.bytes` | `1073741824` | 1 GiB segment 기본값 |
| topic `retention.ms` / `retention.bytes` | override 없음 | broker 기본값 상속 |
| topic override | `max.message.bytes=5242880`만 존재 | retention override가 아님 |

Kafka의 segment 삭제는 비동기이므로 `168 hours`를 메시지별 정확한 보존 시간으로 해석하지 않는다.
실측 가능한 복구 범위는 다음과 같다 (`DEV_OBSERVED`).

- earliest offset: `46325` inclusive
- latest offset: `50423` next offset, 따라서 마지막 존재 offset은 `50422`
- 현재 offset span: `50423 - 46325 = 4098` records
- DataRiver ledger의 indefinite retention은 이 Kafka recovery window와 별개인 향후 application
  계약이다. 현재 DEV에 ledger가 구현되었다는 뜻이 아니다.

## 실제 DEV runtime topology

### 관찰 결과

- DataRiver web: native `node poc-server.mjs` 한 process (`PID 45143`), `*:39080` 한 listener.
- process CWD: `/Volumes/SSD_Mac/workspace/datariver_poc_v0/frontend`.
- CWD checkout은 관찰 시 `b0b666a7e3b78fca96e8b19312599ae3a5624fa3`이고 clean이었지만, process는
  그 이전에 시작되었고 실행 artifact에 source SHA가 내장되지 않았다. 따라서 실행 중 code의 exact
  SHA는 `UNATTESTED`; 이 관찰은 topology/status evidence만 제공한다.
- `datariver-poc` Compose의 `web` container replica는 `0`; Neo4j, pgvector, Redis는 각각 한
  container로 healthy였다. 선언된 web 서비스는 `restart: unless-stopped`, `stop_grace_period: 10s`지만
  현재 native process에는 이 restart policy가 적용되지 않는다.
- `poc-server.mjs`에는 cluster/worker thread가 없다. catalog embedding refresh는 startup 또는
  request에서 호출되는 동일 process의 promise이며 periodic timer가 아니고 오류를 catch한다.
- 현재 source에는 MCL loop, PostgreSQL advisory lock, durable lease/fence, `SIGTERM`/`SIGINT` drain,
  HTTP server close, state-store pool/Redis close가 없다 (`DEV_OBSERVED_SOURCE`).
- Airflow는 별도 한 container에서 standalone, scheduler, API server, DAG processor, triggerer와
  LocalExecutor worker들을 실행하고 `restart: unless-stopped`이며 restart count는 `0`이었다. 이는 기존
  bulk-registration scheduler이며 ADR-0123의 canonical MCL checkpoint owner가 아니다.

### 선택한 실행 위치

- selected runtime location: `CONDITIONAL_EXISTING_WEB_PROCESS_CONTROLLER`
- new container/service required: `NO`
- rationale: 단일 Node web process에 consumer를 무조건 내장하지 않는다. 먼저 기존 process 안에
  명시적 lifecycle controller를 두고 current projection과 partition checkpoint를 같은 PostgreSQL
  transaction boundary에서 처리해야 한다. Airflow에 장기 Kafka consumer를 넣으면 별도
  scheduler/process authority와 failure model이 생기므로 선택하지 않는다.
- singleton: `NOT_IMPLEMENTED`. 각 web replica가 시작할 수 있으므로 PostgreSQL advisory lock과 만료
  가능한 durable lease/fence가 모두 구현·검증되어야 한다.
- failure isolation: `NOT_IMPLEMENTED_FOR_MCL`. consumer 오류를 HTTP process crash로 전파하지 않는
  abortable background controller, partition별 transaction/checkpoint, bounded retry와 health state가
  필요하다.
- graceful shutdown/restart: `NOT_IMPLEMENTED/UNVALIDATED`. signal 수신 시 fetch 중단, in-flight DB
  transaction 정리, checkpoint 전진 여부 확정, lease 해제/만료, HTTP와 pool 종료가 검증되어야 한다.
  현재 native DEV process에는 supervisor restart도 없다.

따라서 위치 선택은 새 container/service를 승인하지 않지만 구현 준비 완료를 뜻하지 않는다. target
Kafka/Avro dependency, singleton/fence, drain, restart/catch-up 증거가 없으므로 T04는 계속
`BLOCKED_TARGET_RECHECK`다.

## TARGET_RECHECK checklist

아래 command는 credential을 포함하지 않는 symbolic/read-only 형태다. TARGET `v1.6.0rc1`에서 별도로
실행하고 DEV 결과를 PASS로 이월하지 않는다. 아래 여섯 항목의 현재 상태는 모두
`RECHECK_REQUIRED`다.

1. **runtime/source identity** — location: approved TARGET host; command:
   `docker inspect <TARGET_DATAHUB_CONTAINER> --format '{{.Config.Image}}'` 및 배포 manifest의 exact SHA
   조회; evidence: DataHub image/version과 DataRiver release SHA; PASS: 승인 manifest와 exact match.
2. **broker/topic retention** — location: TARGET Kafka admin tooling; command:
   `kafka-configs --bootstrap-server <TARGET_BROKER> --describe --entity-type brokers --entity-name <BROKER_ID> --all`
   및 `kafka-configs --bootstrap-server <TARGET_BROKER> --describe --entity-type topics --entity-name MetadataChangeLog_Versioned_v1`;
   evidence: cleanup, retention time/bytes, segment, topic overrides; PASS: 승인 outage/catch-up 창을 수용.
3. **offset recovery window** — location: TARGET Kafka tooling; command:
   `kafka-get-offsets --bootstrap-server <TARGET_BROKER> --topic MetadataChangeLog_Versioned_v1 --time earliest`
   와 동일 command의 `--time latest`; evidence: partition별 inclusive earliest/next latest와 시간 표본;
   PASS: backfill/catch-up 동안 first checkpoint가 retention 안에 남는다는 측정 근거.
4. **schema와 bounded payload** — location: TARGET Schema Registry/Kafka tooling; command:
   subject latest metadata를 field-list만 출력하고, 승인된 명시적 `<PARTITION>/<OFFSET>`에서
   `--max-messages 1 --consumer-property enable.auto.commit=false`로 읽어 동일 sanitizer에 전달;
   evidence: field/type/hash/size와 created time/actor, group before/after; PASS: decode 성공, raw payload
   비보존, 기존 group offset 불변.
5. **consumer ownership/topology** — location: TARGET DataRiver runtime; command:
   `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'`, exact service replica/process 목록과
   source의 lock/lease/signal handler 정적 검사; evidence: web replica 수, 한 active fenced owner,
   failure-contained loop, graceful drain; PASS: split brain과 blind checkpoint advance가 불가능.
6. **restart/catch-up** — 이 Task에서는 restart를 실행하지 않는다. 별도 승인된 change window에서 만든
   restart test의 read-only log/checkpoint/ledger evidence를 조회한다; PASS: 동일 source identity에서
   마지막 contiguous checkpoint부터 dedup replay하고 gap/임의 reset 없이 catch-up. 증거가 없으면
   `TARGET_RECHECK_REQUIRED` 유지.

## 실행 명령

- `git rev-parse HEAD`, `git status --short`, `rg`/`sed`로 허용된 repository evidence와 source 확인
- `docker ps --format ...`, field-limited `docker inspect`, `docker top`, `pgrep`, `ps`, `lsof`
- `kafka-topics --describe --topic MetadataChangeLog_Versioned_v1`
- `kafka-configs` topic 및 broker effective 설정 조회
- `kafka-get-offsets ... --time earliest|latest`
- `kafka-consumer-groups --describe --group generic-mae-consumer-job-client` 전/후 조회
- Schema Registry latest subject를 `jq`로 field/type만 제한 출력
- `kafka-avro-console-consumer`의 명시적 partition/offset, bounded max message, auto commit disabled
  decode를 in-memory sanitizer와 연결

## NOT_EXECUTED

- product code/config/migration/dependency/lockfile 변경과 product test
- DataHub metadata/config/provider data 변경
- Kafka topic/group/offset 생성·수정·삭제·reset·commit
- container start/stop/restart/create/delete와 runtime process signal
- raw aspect/payload 또는 credential 출력·보존
- TARGET/PREP/OPS probe 또는 mutation
- merge, push, G1/G2/G3/G4 승인
