# MCL-COVERAGE-T02 구현 증적

- **Task or Receipt Identity:** MCL-COVERAGE-T02-IMPLEMENTATION / task_6564a8c4a29c / ctx_5709041b2c41
- **Exact SHA:** 737cee10daaf3af1680e11cdb43b2779d0865756
- **Result or Evidence SHA:** a9622e06621d39fd97e5197d2d515e9176204148 (product)
- **Environment:** Node v25.9.0, Docker Linux/arm64, 2026-08-15 KST
- **Result:** PASS_LOCAL_SOURCE

## 구현 및 primary-source 근거

`poc-mcl-capture.mjs`는 DataHub v1.6.0 `SchemaField`/`EditableSchemaFieldInfo` 계약대로 `fieldPath`, `nativeDataType`, nullable(누락 시 false), bounded logical union discriminator, description, `globalTags.tags[].tag`, `glossaryTerms.terms[].urn`을 정규화했다. logical union은 공식 13개 discriminator 중 정확히 하나의 plain object만 허용하고 unknown/multiple/non-object는 fail-closed한다.

- [SchemaField.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaField.pdl)
- [EditableSchemaFieldInfo.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/EditableSchemaFieldInfo.pdl)
- [SchemaFieldDataType.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaFieldDataType.pdl)
- [Status.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/common/Status.pdl)
- [MetadataChangeProposal.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/mxe/MetadataChangeProposal.pdl)
- [ChangeType.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/events/metadata/ChangeType.pdl)

fieldPath/URN 조합은 `field-metadata:<sha256>` entity key로 bounded 처리하고 full field_path/tag_urn/term_urn은 bounded before/after에 보존했다. fieldPath 또는 asset URN 변경은 inferred rename 없이 DELETE+CREATE만 기록한다.

`status.removed`의 정확한 false→true DELETE와 true→false CREATE만 lifecycle ledger로 기록한다. initial status와 lifecycleStage는 추정하지 않으며, aspectName 없는 dataset entity CREATE/CREATE_ENTITY/DELETE는 지원하고 UPSERT는 create로 추정하지 않아 zero event다. raw aspect는 저장하지 않는다.

## current projection 및 DB 계약

generation B(2→1)에서 삭제 URN이 Search, Tree, Chat exact, vector evidence에서 제외되고 generation C에서 동일 URN이 재노출되는 HTTP focused test를 추가했다. current inventory double의 `appendChangeHistory` 호출은 0으로 assertion하여 history ledger와 authoritative current projection이 분리됨을 확인했다.

새/기존 PostgreSQL volume 모두 `ck_poc_change_history_ledger_category_v2` 계약을 사용한다. old 이름이 있을 때만 한 번 DROP하고 v2가 없을 때만 한 번 ADD하므로 두 번째 startup은 category CHECK DDL을 발행하지 않는다. Node startup SQL과 static init SQL은 동일하며 `pg_get_constraintdef`에 의존하지 않는다. LIFECYCLE은 server allowlist, history client decoder/type, Monitoring generic category filter 및 zero-count summary fixture까지 통과한다.

## 실행 결과

| 검증 | 결과 |
| --- | --- |
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | PASS (26/26) |
| `node --test poc-server.test.mjs` | PASS (14/14) |
| B/C Search·Tree·Chat·vector focused test | PASS (1/1) |
| ChangeHistory API + Monitoring Vitest | PASS (2 files, 17 tests) |
| `npm run lint`, `npm run typecheck`, `npm run build:poc` | PASS (기존 chunk-size advisory만 출력) |
| `git diff --check`, allowlist, package.json/package-lock diff | PASS |

`node --test poc-catalog-performance.test.mjs` 전체에서는 범위 밖 기존 shutdown 두 건(`aborts a partial startup inventory refresh...`, `aborts embedding work...`)이 실패했으나, 이번 B/C test와 나머지 catalog projection tests는 PASS다. 이 두 실패는 product 변경 전에도 동일하게 재현된 Node v25.9.0 환경의 PRE_EXISTING 항목이며 허용 범위 밖 shutdown 동작은 수정하지 않았다.

## 제한 및 재검증

- **NOT_EXECUTED:** Node 22/Linux AMD64 Docker build. 현재 실행기는 Node v25.9.0 및 Docker `linux/arm64`이므로 대상 ABI가 아니다.
- **NOT_EXECUTED:** DB/Kafka/DataHub/PREP/OPS runtime mutation. PREP evidence는 `7e941d2:.orchestration/evidence/PREP-MCL-RUNTIME-EVIDENCE.md` USER_EXECUTED fixture/contract로만 사용했다.
- **Unsupported:** non-dataset no-aspect entity lifecycle, no-aspect UPSERT create 추정, ambiguous initial status/lifecycleStage, raw aspect 저장, inferred column/asset rename.
