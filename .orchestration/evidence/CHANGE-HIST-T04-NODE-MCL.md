# CHANGE-HIST-T04 Node POC MCL capture evidence

- 상태: `IMPLEMENTED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`
- 검증일: 2026-08-14 (KST)
- exact base: `9fb7deaa88dfd03d6604ecfd5e86b3c8a8c69a83`
- product commit: `5cc3652cdc82d2a033edd95003e0f5f6525c7e0e`
- 브랜치/worktree: `Ever-Real/change-hist-t04-node-mcl` /
  `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t04-node-mcl`
- 검증 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`
- architecture deviation: 없음

## 구현 계약

- `poc-mcl-capture.mjs`는 호출 시 한 번만 실행되는 dependency-injection형 bounded consumer다.
  admin read로 partition별 현재 high watermark를 먼저 고정하고, PostgreSQL durable `next_offset`을
  canonical resume 위치로 사용한다. Kafka auto-commit은 비활성화하며 background daemon, scheduler,
  service 또는 container를 추가하지 않았다.
- consumer group join/rebalance 때마다 아직 완료되지 않은 partition을 현재 DB checkpoint로 seek한다.
  checkpoint가 retention low보다 뒤면 `HISTORY_GAP`, high보다 앞이면 invalid checkpoint로 fail closed한다.
  고정 high watermark까지의 합계는 구성된 message bound를 넘을 수 없다.
- 선택한 Schema Registry package의 `decode()`를 통해 Confluent magic-byte/schema-id framed Avro를
  decode한다. `GenericAspect.value`의 bounded JSON만 메모리에서 읽고 raw MCL/aspect document를
  persistence나 log에 남기지 않는다.
- 지원 aspect는 `schemaMetadata`, `editableSchemaMetadata`, `datasetProperties`, `globalTags`,
  `glossaryTerms`, `ownership`으로 닫혀 있다. intermediate category는 `SCHEMA_CHANGE`와
  `METADATA_CHANGE`뿐이며, 기존 T03N 저장 vocabulary에 맞춰 persistence adapter에서만
  `TECHNICAL_SCHEMA`/`DOCUMENTATION`/`TAG`/`GLOSSARY_TERM`/`OWNERSHIP`으로 변환한다.
- schema field 또는 metadata association 한 source record는 여러 intermediate ledger event로 fan-out될
  수 있다. 기존 T03N source/partition/offset/ordinal identity와 transaction을 재사용하므로 replay
  idempotency, duplicate suppression, distinct same-field change 보존이 유지된다.
- unsupported aspect는 decode된 aspect body를 열지 않고 zero-ledger-event transaction으로 offset만
  안전하게 인정한다. 이를 위해 `poc-state-store.mjs`가 0-event capture와 read-only checkpoint 조회를
  지원하도록 최소 조정되었다. ledger insert/zero-event acknowledgement와 checkpoint advance는 모두
  같은 PostgreSQL transaction이다.
- malformed supported record, non-contiguous offset, decode/normalization/DB failure는 checkpoint를
  전진시키지 않는다. Kafka/Schema Registry/DB credential, broker, topic, group/client id, TLS 및 limits는
  config/environment boundary 소유이며 raw payload와 credential logging 경로가 없다.

## dependency 및 lock evidence

승인된 direct dependency 두 개만 exact pin으로 추가했다.

| dependency | exact version | lock integrity | license evidence | native binary |
|---|---:|---|---|---|
| `kafkajs` | `2.2.4` | `sha512-j/YeapB1vfPT2iOIUn/vxdyKEuhuY2PxMBvf5JWux6iSaukAccrMtXEY/Lb7OvavDhOWME589bpLrEdnVHjfjA==` | package manifest `MIT` | 없음 |
| `@kafkajs/confluent-schema-registry` | `4.1.0` | `sha512-0/OM85fT66zsi+eBE56FnmdI2qAKBkhiXIYKnB4q1jB0AvUucRBvyqmld0l05q0r2FIODa0NG9612dLblxxI5Q==` | package manifest field 없음; 배포된 `LICENSE` 파일은 MIT text | 없음 |

- `frontend/package-lock.json` SHA-256:
  `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`
- `npm install --save-exact kafkajs@2.2.4 @kafkajs/confluent-schema-registry@4.1.0` 결과:
  369 packages audited, vulnerability 0.
- direct package tree에서 `.node` native binary 없음. registry subtree는 pure-JS Avro/JSON/Protobuf
  decoder 의존성을 포함한다.
- registry package의 manifest license field가 비어 있으므로 PREP offline artifact 생성 시 exact lock,
  checksum, license file 및 SBOM을 Linux AMD64/Node 22.19+에서 다시 확인해야 한다. 이 DEV evidence는
  그 target gate를 대체하지 않는다.

## 실행 검증

| 명령 | 결과 |
|---|---|
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | 최종 PASS 10/10 |
| `npx eslint poc-mcl-capture.mjs poc-mcl-capture.test.mjs poc-state-store.mjs poc-state-store.test.mjs` | PASS |
| `npm run lint` | PASS, 전체 frontend ESLint |
| `npm run build:poc` | PASS; 기존 500 kB chunk warning만 존재 |
| `npm run test:poc-server` | PASS 28/28 |
| `git diff --check` / staged diff check | PASS |
| credential/raw logging 정적 scan | PASS |
| direct dependency `.node` file scan | PASS, 없음 |

첫 focused run은 6/10 PASS였다. 실제 `avsc` record prototype을 plain object로만 제한한 test boundary와
zero-event test의 마지막 SQL assertion 순서 때문에 4건이 실패했고, Avro record object를 한정 수용하고
assertion을 transaction 직후로 이동한 뒤 최종 10/10 PASS를 반복 확인했다. 이후 실제 형태의
`GenericAspect.value` Avro wrapper와 group-join DB checkpoint seek를 보강한 뒤에도 10/10 PASS였다.

## NOT_EXECUTED / 잔여 gate

- live DEV Kafka/MCL/Schema Registry read: 안전한 기존 sample/config를 이 Task에서 제공받지 않아
  `NOT_EXECUTED`; unit contract를 live evidence로 승격하지 않는다.
- live PostgreSQL DDL/transaction/concurrency 및 active POC runtime invocation: runtime/DB mutation 없이
  `NOT_EXECUTED`.
- Node `22.19+`, Linux AMD64 PREP offline npm artifact/checksum/SBOM/license 재검증:
  `TARGET_RECHECK_REQUIRED`.
- target topic retention, partition assignment/consumer-group 충돌, actual schema subject/version,
  first exact checkpoint 및 outage/catch-up: `BLOCKED_TARGET_RECHECK`.
- Python/Alembic T03 integration, UI/API/CR state, service/container/scheduler/provider configuration mutation:
  `NOT_EXECUTED`; 기존 Python T03은 `NOT_RUNTIME_INTEGRATED` 상태로 보존했다.
- merge, push, PREP, OPS: `NOT_EXECUTED`; G1/G2/G3/G4는 모두 `NOT_APPROVED`.

로컬 제품 구현 blocker는 없다. 다음 최소 단계는 독립 검증 후 exact candidate에 대한 G1 판단이며,
runtime 활성화는 별도의 TARGET 재검증을 모두 통과하기 전까지 차단된다.
