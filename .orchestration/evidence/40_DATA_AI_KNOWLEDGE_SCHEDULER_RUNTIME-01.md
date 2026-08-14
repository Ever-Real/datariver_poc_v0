# 40_DATA_AI_KNOWLEDGE_SCHEDULER_RUNTIME-01 DEV 런타임 증적

## 결론

`PASS_RUNTIME_LIMITED` — 단일 임시 Node 22 후보에서 KST 2026-08-15 00:00 경계의 startup catch-up이 실제 MCL capture와 Catalog reconciliation 뒤 durable scheduler receipt를 기록했다. 동일 경계 재시작은 receipt, semantic ledger, checkpoint를 추가하거나 후퇴시키지 않았다. 실제 자정 timer 발화는 관찰하지 않았으므로 `NOT_EXECUTED / DAILY_CLOCK_NOT_OBSERVED`다.

## 기준과 범위

- Task: `task_b85fdb6d67ed` / `40_DATA_AI_KNOWLEDGE_SCHEDULER_RUNTIME-01`
- evidence base HEAD: `9a7eb985323f493a7e24868140e43b9e24d0e30d` (시작 시 clean)
- exact product revision/image label: `061c6c20e5bcdbd65c884ff4b428c0f73ac17276`
- Node image: `node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90`
- 실행 model: 지정 fallback `gpt-5.6-terra High` (Gemini/Antigravity 재시도·교체 없음)
- 후보: `datariver-poc-scheduler-runtime-01` 한 개만 생성; `datariver-poc-services` 및 `datahub_network`만 연결, host port 미공개
- 39083의 실제 환경을 값 출력 없이 상속했다. runtime delta는 internal `broker:29092`, `schema-registry:8081`, `datahub-gms:8080`, scheduler enabled, `Asia/Seoul`, 승인된 MCL source/schema contract 및 필수 일회성 consumer identity뿐이다. credential, raw payload, provider 문서는 출력·저장하지 않았다.

Schema Registry SHA-256은 제품이 요구하는 64-hex canonical 값 `d229d56f93936b990625d8f4a3d99750e59150438d29570705f1f1031670d7fe`를 사용했다. Controller 전달 문자열의 끝 `5`는 SHA-256 길이 밖이므로 환경에 사용하지 않았다. source identity는 `62db387b0627a5f4ab5aecaa36c9985565b429f5776d86ecd708e5bfba78d802`, topic은 `MetadataChangeLog_Versioned_v1`이다.

## 실제 catch-up 및 순서

후보 startup 뒤 scheduler receipt만 최대 8분으로 polling했고, 약 1분 안에 아래 row를 관찰했다.

| scope | last successful schedule | trigger | state version |
|---|---|---|---:|
| `change-history-scheduler-v1:datariver:poc:change-history-scheduler:v1` | `2026-08-14T15:00:00.000Z` | `scheduled` | 1 |

이는 KST `2026-08-15 00:00:00` 경계다. 제품 실행 경로에서 receipt write는 PostgreSQL advisory lock 아래에서 `captureMcl()`과 `startDatahubInventoryRefresh()`가 모두 정상 반환한 뒤에만 수행된다. 따라서 위 durable receipt는 실제 capture와 catalog reconciliation이 receipt보다 먼저 완료됐음을 보인다. DataHub metadata, CR, topic/offset reset, 별도 service/proxy/framework는 만들거나 변경하지 않았다.

첫 receipt 직후 source-specific durable 상태는 source `1`, semantic ledger `13`, checkpoint `1`이었다. checkpoint는 `partition=0`, `next_offset=51864`, `version=50`이었다.

## 동일 경계 재시작 억제

동일 후보만 stop/start 하여 같은 KST boundary startup을 다시 실행했다. 이후 receipt만 세 번 polling했고 매번 schedule/trigger/version은 위 행과 동일했다. 재시작 전후 값도 동일했다.

| 관찰 | 재시작 전 | 재시작 후 | 판정 |
|---|---:|---:|---|
| scheduler receipt version | 1 | 1 | duplicate/version unexpected 없음 (`already_completed`) |
| semantic ledger count | 13 | 13 | +0 |
| checkpoint `(partition:next_offset:version)` | `0:51864:50` | `0:51864:50` | 후퇴 없음 |

HTTP manual trigger는 제공되지 않아 만들거나 흉내 내지 않았다. 안전한 live concurrent trigger도 없었다. source-test fallback은 host에 기존 `pg` package가 없어 의존성 설치 없이 실행할 수 없었으므로 동시 lock contention은 `NOT_EXECUTED`로 분리한다. 이것은 위 single-candidate advisory-lock receipt/restart 결과를 concurrent proof로 과장하지 않는다는 뜻이다.

## 경계와 정리

- 실제 midnight timer event: `NOT_EXECUTED / DAILY_CLOCK_NOT_OBSERVED`.
- 후보 컨테이너와 task-owned `datariver-poc:scheduler-runtime-061c6c2` 이미지는 제거했다.
- 기존 `datariver-poc-web-1`은 39083에서 healthy였고, Neo4j/pgvector/Redis 및 DataHub GMS/Schema Registry/broker도 모두 unchanged/healthy로 남았다. 기존 39080은 건드리지 않았다.
- 제품 source, package/lock, metadata, CR, provider data, DataHub/Kafka service, proxy, PREP, OPS, publication은 변경하지 않았다.
