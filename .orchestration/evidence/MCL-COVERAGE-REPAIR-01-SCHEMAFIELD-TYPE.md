# MCL-COVERAGE-REPAIR-01 SchemaField type 보수 증적

- **Task / Dispatch:** `MCL-COVERAGE-REPAIR-01-SCHEMAFIELD-TYPE` / `task_db291bef24c2` / `ctx_a7380ef0ba2d`
- **Exact base SHA:** `042f8a2e3c066407411f9fd196f5ac4ef18f9972`
- **Product parent SHA:** `a9622e06621d39fd97e5197d2d515e9176204148`
- **Product commit SHA:** `4743d29a9e00a103b71f3485cd5baf0ad9cf48d5`
- **환경:** Node `v25.9.0`, 2026-08-15 KST
- **판정:** `PASS_LOCAL_SOURCE`, `PREP_TARGET_RECHECK_REQUIRED`

## 보수 내용

`SchemaField.type`는 DataHub v1.6의 두 단계 `SchemaFieldDataType` 형상만 수용하도록 바꿨다. 바깥 plain object는 정확히 `type` 하나만 가져야 하고, 안쪽 union도 정확히 하나의 `com.linkedin.schema.*Type` discriminator와 plain-object payload만 가져야 한다. 공식 13개 discriminator를 bounded canonical leaf name(`BooleanType`부터 `RecordType`)으로 결정적으로 정규화하며, 이전 one-level fixture, 바깥 추가 member, 누락/비객체 inner type, unknown/multiple discriminator, 비객체 payload는 모두 fail-closed한다.

`nativeDataType`는 이제 누락 또는 null로 canonicalize되지 않는다. 기존 strict bounded string 계약과 500자 limit을 그대로 사용해 비어 있음, 비문자열, 초과 길이를 거부하며, description의 empty-to-null 처리, nullable 누락 시 false, fieldPath identity, tags/terms, lifecycle, event ordering/dedup 및 raw aspect 비저장은 변경하지 않았다.

공식 계약 근거는 [DataHub v1.6.0 SchemaField.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaField.pdl) 및 [SchemaFieldDataType.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaFieldDataType.pdl)이다.

## 변경 경계

- `frontend/poc-mcl-capture.mjs`
- `frontend/poc-mcl-capture.test.mjs`

제품 커밋에는 위 두 파일만 들어 있다. dependency, `package.json`, `package-lock.json`, DB/schema/server/UI/config, PREP/OPS/runtime, push/merge는 변경하거나 실행하지 않았다.

## 검증

| 검증 | 결과 |
| --- | --- |
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | PASS (27/27) |
| 모든 공식 13개 logical discriminator | PASS |
| required `nativeDataType`: missing/empty/non-string/501 chars | PASS (fail-closed) |
| invalid wrapper/union 및 old one-level fixture | PASS (fail-closed) |
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm run build:poc` | PASS (기존 Vite chunk-size advisory만 출력) |
| `git diff --check`, exact allowlist, package/lock diff | PASS |

이 parser 보수는 server/catalog 경로를 호출하거나 변경하지 않으므로, 해당 focused regression은 의도적으로 확장하지 않았다.

## 남은 재검증

`PREP_TARGET_RECHECK_REQUIRED`: 허가된 PREP/TARGET 환경에서 실제 DataHub v1.6 MCL을 대상으로 계약 형상과 capture/ledger/checkpoint 경계를 재검증해야 한다. 본 작업은 로컬 source 검증만 수행했으며 DB, Kafka, DataHub, PREP/OPS runtime mutation과 publish/merge는 수행하지 않았다.
