# PREP-READINESS-MCL-061C 독립 검증 증적

## 판정

`PASS_LOCAL_VALIDATION / PREP_TARGET_RECHECK_REQUIRED`.

`0b53d79702a0c2a4f5a83fdf12a22e0a46cd107d`에서 요청된 로컬 재검증은 모두 통과했다. 이는
PREP host 또는 Kafka/Schema Registry 대상 runtime 검증이 아니며, source repair·push·merge·PREP·OPS
변경을 포함하지 않는다. G1, G2, G3, G4는 모두 `NOT_APPROVED`다.

## 기준선과 계보

- 시작/종료 HEAD: `0b53d79702a0c2a4f5a83fdf12a22e0a46cd107d`.
- branch: `Ever-Real/prep-readiness-mcl-061c-validation`; 시작 전과 docs commit 전 작업트리는 clean이었다.
- `061c6c20e5bcdbd65c884ff4b428c0f73ac17276`은 현재 HEAD의 ancestor다.
- 정확한 제품 commit `061c^..061c`의 변경은 다음 네 경로뿐이다.

  - `frontend/package.json`
  - `frontend/package-lock.json`
  - `frontend/poc-mcl-capture.mjs`
  - `frontend/poc-mcl-capture.test.mjs`

- `061c..0b53d79` 범위는 `.orchestration/evidence/**`와 `.orchestration/receipts/**`만 변경했다.
  제품 경로의 후속 변경은 없다.

## 새로 실행한 제한 검증

| Gate | 결과 | 실제 결과 |
| --- | --- | --- |
| fresh dependency install | PASS | `frontend/npm ci --ignore-scripts`: 370 packages, audit vulnerabilities 0 |
| package/lock exact pin | PASS | manifest와 lock root 모두 `kafkajs-snappy` `1.1.0`; resolved package도 `1.1.0`, MIT, install script 없음 |
| transitive consistency | PASS | `kafkajs-snappy`의 `snappyjs ^0.6.0`은 lock에서 `0.6.1` MIT, install script 없음으로 해석됨 |
| focused MCL | PASS | `node --test poc-mcl-capture.test.mjs`: 7/7 |
| focused scheduler | PASS | `node --test poc-change-history-scheduler.test.mjs`: 4/4 |
| Dockerfile.example runtime COPY closure | PASS | runtime entry/동적 import의 `poc-server.mjs`, `poc-state-store.mjs`, `poc-change-history-scheduler.mjs`, `poc-mcl-capture.mjs`, package, production `node_modules`, assets가 image에 존재; missing 0 |
| Linux/AMD64 image build | PASS | `docker build --platform linux/amd64 --pull=false -f deploy/poc/Dockerfile.example`; image inspect `linux/amd64` |
| Node 22 image Snappy | PASS | image 내부 `v22.19.0`; `poc-mcl-capture.mjs` import 후 KafkaJS Snappy codec 등록 및 compress/decompress round-trip 성공 |

요청 범위를 넘는 lint, typecheck, broad server regression, PREP Compose lifecycle, provider/runtime test는 실행하지 않았다.

## 독립 정적 점검

- Snappy 등록은 MCL Kafka boundary의 `CompressionCodecs[CompressionTypes.Snappy]` 한 곳이다.
  변경 diff에서 새 deployment endpoint, host, topic, credential literal 또는 timezone hardcoding은 발견되지 않았다.
- 변경된 focused test는 codec 동일성 및 round-trip assertion을 추가했으며, `skip`, `only`, `todo`, assertion 삭제 또는 validator/guard 완화는 발견되지 않았다.
- credential 값은 읽거나 기록하지 않았다. password 관련 source 식별자는 환경 변수 읽기 및 완전성 validation뿐이다.
- `deploy/poc/Dockerfile.example`은 scheduler와 MCL module COPY를 모두 포함한다. 이 checkout에서
  ignored `deploy/poc/Dockerfile.local`은 없고 tracked file도 아니다. 이전 PREP 증적에 기록된
  local Dockerfile의 두 COPY 누락은 이 작업에서 읽거나 변경하지 않았으므로 PREP host에서 별도 drift
  재확인이 필요하다.

## PREP env/network delta — 이름만

Compose `web`은 `poc-services` 한 network에 연결하며 그 실제 이름은
`POC_SHARED_NETWORK`로 선택되고 기본값은 `datariver-poc-services`다. Kafka와 Schema Registry는
Compose service/network로 추가되지 않고 web 환경 binding으로 전달된다. 따라서 PREP에서는 container
관점의 broker advertised listener와 Schema Registry 도달성을 값 비노출 방식으로 다시 검증해야 한다.

변경 기능의 scheduler binding은 `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID`,
`POC_CHANGE_HISTORY_SCHEDULER_ENABLED`, `POC_CHANGE_HISTORY_SCHEDULER_TIME_ZONE`,
`POC_CHANGE_HISTORY_SCHEDULER_LOCK_NAME`이다. MCL binding은 `POC_MCL_KAFKA_BROKERS`,
`POC_MCL_KAFKA_CLIENT_ID`, `POC_MCL_KAFKA_GROUP_ID`, `POC_MCL_KAFKA_TOPIC`,
`POC_MCL_SOURCE_IDENTITY_HASH`, `POC_MCL_SCHEMA_CONTRACT_HASH`, `POC_MCL_PROVIDER_NAME`,
`POC_MCL_PROVIDER_VERSION`, `POC_MCL_KAFKA_SSL`, `POC_MCL_KAFKA_SASL_MECHANISM`,
`POC_MCL_KAFKA_SASL_USERNAME`, `POC_MCL_KAFKA_SASL_PASSWORD`,
`POC_MCL_SCHEMA_REGISTRY_URL`, `POC_MCL_SCHEMA_REGISTRY_USERNAME`,
`POC_MCL_SCHEMA_REGISTRY_PASSWORD`, `POC_MCL_MAX_MESSAGES`,
`POC_MCL_MAX_RECORD_BYTES`, `POC_MCL_TIMEOUT_MS`다. 어떤 값이나 credential도 검사·기록하지 않았다.

## 정리와 한계

- task-local image `datariver-prep-readiness-mcl-061c-validation:task_0b0e770a56d7`을 제거했다.
  image 기반 task container는 모두 `--rm`으로 실행되어 잔존하지 않았다.
- `NOT_EXECUTED`: PREP/OPS runtime, Compose up/down, Kafka/Schema Registry target connection,
  env-file 값 확인, Dockerfile.local host file 읽기, provider/metadata/CR 변경, source repair,
  push, merge, publication.
- 권고: G1/G2 승인 전 PREP AMD64에서 exact source SHA, local Dockerfile COPY closure,
  non-secret env binding, broker/SR reachability 및 scheduler runtime을 별도 검증한다. 이 로컬 PASS는
  target runtime PASS 또는 release approval을 대체하지 않는다.
