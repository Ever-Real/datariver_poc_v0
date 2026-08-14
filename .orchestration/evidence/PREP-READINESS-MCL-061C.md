# PREP-READINESS-MCL-061C 증적

## 결론

`LOCAL_PREP_CANDIDATE_READY / PREP_TARGET_RECHECK_REQUIRED`.

제품 revision `061c6c20e5bcdbd65c884ff4b428c0f73ac17276`의 Snappy 보수와 이 작업에서
cherry-pick한 scheduler 증적은 로컬 source, Linux/AMD64 Docker build 및 image 내부
검증까지 통과했다. 그러나 PREP host, 네트워크, 환경 값, Kafka/Schema Registry 연결과
runtime은 실행하거나 바꾸지 않았다. 그러므로 G1–G4는 모두 `NOT_APPROVED`이며, 이 문서는
push/merge/배포 승인이 아니다.

## 기준선·계보

- 시작 HEAD/branch: `29dae9909ffde394d99f80a0d0e53372f26a22b8` /
  `Ever-Real/prep-readiness-mcl-061c`, clean.
- scheduler evidence 원본 commit `f6d432e1c8c831455d2cd56b2c0e0fa8625e1dec`만
  cherry-pick하여 local commit `e9bb4431c6388e1aa1e660aeda3f07e9bbfd1926`을 만들었다.
  원본 diff는 `.orchestration/evidence/40_DATA_AI_KNOWLEDGE_SCHEDULER_RUNTIME-01.md`와
  `.orchestration/receipts/40_DATA_AI_KNOWLEDGE_SCHEDULER_RUNTIME-01.md` 두 문서 추가뿐으로,
  product path는 0개였다.
- `061c…`부터 cherry-pick 직전 candidate까지의 commit은 `9a7eb985`, `a7ddd39e`,
  `29dae990`의 evidence/receipt 전용 세 개였다. cherry-pick 뒤 범위도 여섯 개의
  `.orchestration/evidence/**` 또는 `.orchestration/receipts/**` path뿐이다.
- 정확한 제품 diff `061c…^..061c…`는 아래 네 path만 수정했다.

  - `frontend/package.json`
  - `frontend/package-lock.json`
  - `frontend/poc-mcl-capture.mjs`
  - `frontend/poc-mcl-capture.test.mjs`

## 로컬 검증

| Gate | 결과 | 실제 근거 |
|---|---|---|
| fresh dependency install | PASS | `frontend`에서 `npm ci --ignore-scripts`; 370 packages, vulnerabilities 0 |
| exact package/lock | PASS | manifest/root lock/resolved lock 모두 `kafkajs-snappy` `1.1.0`; MIT; transitive spec `snappyjs ^0.6.0`, resolved `0.6.1` |
| focused MCL | PASS | `node --test poc-mcl-capture.test.mjs`: 7/7 |
| focused scheduler | PASS | `node --test poc-change-history-scheduler.test.mjs`: 4/4 |
| POC build | PASS | `npm run build:poc` 성공 |
| Docker COPY closure | PASS | `poc-server.mjs` runtime closure의 scheduler/state-store/server 세 module은 모두 Dockerfile.example runtime `COPY`에 있고 missing 0; MCL module도 명시 COPY됨 |
| Linux/AMD64 image | PASS | `docker build --platform linux/amd64 --pull=false -f deploy/poc/Dockerfile.example`; image inspect `linux/amd64` |
| Node 22 image import | PASS | built image의 `node --version`은 `v22.19.0`; `kafkajs-snappy` import 및 Snappy compress/decompress round-trip 성공; image 내부 dependency tree는 `kafkajs-snappy@1.1.0 -> snappyjs@0.6.1` |

빌드와 image 실행은 ARM64 host에서 AMD64 emulation 경고를 냈지만 image inspect가
`linux/amd64`를 확인했다. task-local image
`datariver-prep-readiness-mcl-061c:task_d736cad2f3d7` 및 모든 task-local `--rm`
container를 제거했다.

## PREP 계약: 이름만, 값 미기록

Compose `web`은 `poc-services` network(이름은 `POC_SHARED_NETWORK`로 선택)만 직접
선언한다. Kafka와 Schema Registry의 주소/인증 값은 Compose가 만들지 않고 web 환경에
전달한다. 따라서 PREP에서는 candidate container에서 broker advertised listener와
Schema Registry URL이 실제로 도달 가능한지를 별도 재검증해야 하며, 값·credential은 이
증적에 기록하지 않는다.

MCL/Kafka/SR variable 이름은 다음과 같다.

- `POC_MCL_KAFKA_BROKERS`, `POC_MCL_KAFKA_CLIENT_ID`, `POC_MCL_KAFKA_GROUP_ID`,
  `POC_MCL_KAFKA_TOPIC`, `POC_MCL_SOURCE_IDENTITY_HASH`,
  `POC_MCL_SCHEMA_CONTRACT_HASH`, `POC_MCL_PROVIDER_NAME`,
  `POC_MCL_PROVIDER_VERSION`, `POC_MCL_KAFKA_SSL`,
  `POC_MCL_KAFKA_SASL_MECHANISM`, `POC_MCL_KAFKA_SASL_USERNAME`,
  `POC_MCL_KAFKA_SASL_PASSWORD`, `POC_MCL_SCHEMA_REGISTRY_URL`,
  `POC_MCL_SCHEMA_REGISTRY_USERNAME`, `POC_MCL_SCHEMA_REGISTRY_PASSWORD`,
  `POC_MCL_MAX_MESSAGES`, `POC_MCL_MAX_RECORD_BYTES`, `POC_MCL_TIMEOUT_MS`.

Scheduler variable 이름은 `POC_CHANGE_HISTORY_ACTIVE_SUBJECT_ID`,
`POC_CHANGE_HISTORY_SCHEDULER_ENABLED`, `POC_CHANGE_HISTORY_SCHEDULER_TIME_ZONE`,
`POC_CHANGE_HISTORY_SCHEDULER_LOCK_NAME`이다. Source의 stable minimum activation
contract는 scheduler enabled와 다음 non-empty MCL bindings이다: brokers, client ID,
group ID, topic, source identity hash, schema contract hash, provider name, provider
version, Schema Registry URL. MCL capture는 자신의 전체 required config validation을
통과해야 하며, SASL/SR auth는 설정할 경우 username/password 쌍이 완전해야 한다.
Scheduler는 PostgreSQL과 capture 뒤 Catalog reconciliation이 모두 이용 가능해야
실행된다.

## 기존 PREP local-only drift 및 안정 최소 계약

기존 `PREP-39081-VALIDATION-PENDING` evidence/receipt는 PREP의 ignored
`deploy/poc/Dockerfile.local`이 tracked example에 추가된
`poc-change-history-scheduler.mjs`와 `poc-mcl-capture.mjs` runtime COPY를 빠뜨려
첫 candidate startup이 실패했고, 사용자가 local file만 최소 보완한 뒤 기동했다고
기록한다. 이 task checkout에는 `Dockerfile.local`이 없고 Git tracked file도 아니므로,
그 PREP host-local file을 읽거나 변경하지 않았다.

안정 최소 contract는 tracked `deploy/poc/Dockerfile.example`과 동일하게
`package.json`, production `node_modules`, `dist-poc`, `poc-server.mjs`,
`poc-state-store.mjs`, `poc-change-history-scheduler.mjs`, `poc-mcl-capture.mjs`,
`poc-assets/`를 runtime image에 포함하는 것이다. PREP가 local Dockerfile을 유지하면
이 COPY closure를 release drift check로 비교해야 한다.

## secret/hardcoding 검사

제품 네 path와 candidate evidence/receipt path를 value를 출력하지 않는 정규식 검사와
source diff review로 확인했다. package/lock에 credential literal은 없고, MCL source의
password 관련 match는 환경 변수 읽기와 validation field뿐이며 literal secret은 없다.
evidence/receipt에는 credential 값이 없다. 제품 diff의 deployment-specific
host/IP/endpoint 추가 match는 0개였고, focused test의 invalid broker fixture는
product runtime contract가 아니다. 이전 scheduler evidence의 endpoint/contract 표기는
과거 DEV runtime 사실이며 PREP 값 또는 secret으로 전용하지 않았다.

## 미실행·권고

- `NOT_EXECUTED`: PREP/OPS runtime, Compose up/down, target Kafka/SR connection,
  env-file value inspection, metadata/CR/provider mutation, push, merge, publication.
- `NOT_APPROVED`: G1, G2, G3, G4.
- 권고: source publication 전에는 G1/G2의 명시 승인과 PREP AMD64에서 값 비노출
  broker/SR reachability, exact source/contract hash, scheduler startup catch-up,
  checkpoint monotonicity 및 local Dockerfile COPY-drift 검증을 수행한다. 이 local
  PASS는 target runtime PASS를 대체하지 않는다.
