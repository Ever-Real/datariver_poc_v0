# MCL-COVERAGE-T03 독립 검증 증적

- **Task / Dispatch:** `MCL-COVERAGE-T03-INDEPENDENT-VALIDATION` / `task_a3524574c9be` / `ctx_b3c040f1383c`
- **역할 / 모델:** `50_QUALITY_VALIDATION` / `gpt-5.6-sol High controlled fallback`
- **검증 HEAD:** `fb78713f749ec4afad14eef9a6f72c2f8cd1108d` (검증 시작 시 clean)
- **Product candidate:** `a9622e06621d39fd97e5197d2d515e9176204148`
- **Builder base:** `737cee10daaf3af1680e11cdb43b2779d0865756`
- **환경:** macOS arm64, Node `v25.9.0`, npm `11.12.1`, Docker server Linux/arm64
- **판정:** **FAIL / TARGET_RECHECK_REQUIRED**
- **Product write:** **NONE**

## 차단 finding

### F-01 — 실제 DataHub v1.6 `SchemaField.type` source shape를 거부함

DataHub v1.6 primary PDL에서 `SchemaField.type`은 `SchemaFieldDataType` 레코드이고, 그 레코드 안의 `type`이 13개 logical type union이다. 따라서 실제 JSON은 최소 두 단계인 `field.type.type.<union discriminator>` 구조이다. DataHub의 공식 OpenAPI 예시도 `"type":{"type":{"__type":"StringType"}}` 형태를 사용하고, Rest.li 직렬화는 `"type":{"type":{"com.linkedin.schema.NumberType":{}}}` 형태를 보인다.

- [`SchemaField.pdl`](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaField.pdl): `type: SchemaFieldDataType`, `nativeDataType: string`
- [`SchemaFieldDataType.pdl`](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaFieldDataType.pdl): 내부 `type: union[...]`
- [DataHub 공식 OpenAPI 사용 예](https://github.com/datahub-project/datahub/blob/master/docs/api/openapi/openapi-usage-guide.md)

후보의 `frontend/poc-mcl-capture.mjs:422`는 `logicalType(field.type)`을 호출하고, `:594-604`는 그 객체의 최상위 key가 곧 `BooleanType`/`NumberType` 등이라고 요구한다. 즉 후보 테스트의 합성 fixture인 `type: { NumberType: {} }`만 통과하며 v1.6 실제 2-level source shape는 통과하지 않는다.

독립 probe 입력:

```json
{"fieldPath":"id","nullable":false,"type":{"type":{"com.linkedin.schema.NumberType":{}}},"nativeDataType":"BIGINT"}
```

실행 결과는 exit `42`, 오류 `schemaMetadata.type must be a single supported union discriminator.`였다. 이 오류는 supported MCL 처리 중 발생하므로 해당 Kafka record의 durable checkpoint도 전진하지 않는다. 따라서 실제 v1.6 `schemaMetadata`에서 column ADD/REMOVE, logical/native/nullable/description 및 같은 aspect의 column tag/term coverage를 보장할 수 없다.

같은 source-shape 경계에서 `SchemaField.nativeDataType`은 v1.6 PDL의 required `string`인데 후보 `:421`은 `optionalDocumentString`으로 누락을 `null`로 허용한다. nullable 누락을 `false`로 처리하는 부분은 PDL default와 일치하지만, logical/native source-shape 전체 계약은 충족하지 못한다.

이 finding은 독립 validator 권한상 수정하지 않았다.

## 정적 검토 결과

- ancestry는 `737cee1 -> a9622e0 -> fb78713`으로 정확하며 product diff는 builder가 선언한 13개 경로뿐이다. `fb78713`은 product 이후 evidence-only commit이다.
- product diff에 package/lock 변경은 없고 `package.json`/`package-lock.json` SHA-256은 각각 `d41aa826a203243509e7684eb45a733c7b24a26df0dcf4a0145f05e256d83789`, `534d792566f0e9371ca1c7ca7166acbbdcc801f07146450ff54005b188a28be5`로 install 전후 동일하다.
- product secret, credential, 고정 배포 IP 증가는 없다. 변경된 token/URL 문자열은 local test double 값뿐이다.
- nested field tag/term 경로 자체는 `globalTags.tags[].tag`, `glossaryTerms.terms[].urn`과 일치하며 bounded hash identity, 정렬 기반 ordinal, raw aspect 비저장 경계가 유지된다. 다만 `schemaMetadata` 경로는 F-01 때문에 실제 v1.6 입력에서 도달 불가다.
- fieldPath 변경은 exact DELETE+CREATE이며 asset URN rename을 추정하는 로직은 없다.
- `status.removed` false→true DELETE, true→false CREATE/reactivation, initial/`lifecycleStage` 무추정, no-aspect dataset CREATE/CREATE_ENTITY/DELETE 및 UPSERT 무추정 정책은 코드와 집중 테스트에서 확인했다.
- 기존 table metadata/tag/term/ownership 경로는 유지되고 no-aspect lifecycle은 `entityType === 'dataset'`만 허용한다. MCL `entityType`으로 Table/View subtype을 만드는 경로는 없다.
- PostgreSQL old constraint는 이름으로만 1회 DROP, v2는 없을 때만 1회 ADD하며 Node startup SQL과 init SQL이 일치한다. `pg_get_constraintdef` 또는 파괴적 data DML은 없다. 실제 existing-volume DB startup은 금지 경계 때문에 실행하지 않았다.
- generation B에서 삭제 URN의 Search/Tree/Chat exact/vector 제외, generation C의 동일 URN 재노출, history append 0회, current generation 분리를 focused HTTP test로 확인했다. last-good/atomic/optional Redis 기존 테스트도 통과했다.
- server/client/Monitoring의 `LIFECYCLE` allowlist, category filter, zero-count key, detail before/after 및 기존 category 보존을 확인했다.

## 실행 결과

| 검증 | 결과 |
| --- | --- |
| `npm ci` | PASS — 370 packages, lock unchanged, 0 vulnerabilities |
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | PASS 26/26 (fixture source-shape 한계는 F-01) |
| 실제 v1.6 2-level logical type 독립 probe | **FAIL / F-01 재현**, exit 42 |
| `npm run build:poc` | PASS — 기존 chunk-size advisory만 출력 |
| build 전 `node --test poc-server.test.mjs` | 13/14; dist 미생성으로 root 404 |
| build 후 `node --test poc-server.test.mjs` | PASS 14/14 |
| `node --test poc-catalog-performance.test.mjs` | PASS 5/5; B/C test PASS, 알려진 B-02 shutdown debt는 이번 실행에서 재현되지 않음 |
| ChangeHistory API + Monitoring focused Vitest | PASS 2 files / 17 tests |
| `npm run test:poc-server` | PASS 33/33 |
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm test` | NON_BLOCKING_REPO_TEST_DEBT — 83 files PASS, 5 files FAIL; 4개 `node:test` 파일을 Vitest가 수집해 `No test suite found`, `PocApp.test.tsx` 1개 기존 fetch 기대 실패(후보가 `vitest.config.ts`, `PocApp.test.tsx`, fetch 동작을 변경하지 않음). 관련 focused/node suite는 별도 PASS |
| `git diff --check`, exact path/package/lock 검사 | PASS |

## Docker / runtime / PREP 경계

- **NOT_COMPLETED_NON_AUTHORITATIVE:** 잘못 선택한 `frontend/Dockerfile`에 대해 `--platform linux/amd64 --load` build를 시작했으나 `COPY offline_npm/` 입력 부재로 build stage에서 실패했다. 이는 authoritative POC image가 아니며 image import와 service start는 발생하지 않았다.
- authoritative POC image인 `deploy/poc/Dockerfile.example` build/import는 control-plane 지시에 따라 이 FAIL 후보에서 추가 실행하지 않았다.
- DB/Kafka/DataHub/container service/PREP/OPS mutation은 실행하지 않았다. PREP evidence는 USER_EXECUTED fixture/contract일 뿐 DEV/TARGET PASS로 전환하지 않았다.
- push/merge는 실행하지 않았다.

## 결론 및 재검증 요구

판정은 **FAIL**이다. F-01을 product owner가 수정한 새 candidate에서 DataHub v1.6 실제 2-level union JSON 및 required native type fail-closed fixture를 추가하고 MCL/state-store/server/current-projection suite를 다시 실행해야 한다. 그 뒤 Node 22 Linux/AMD64 authoritative POC image build/import, permitted existing-volume PostgreSQL v2 second-start DDL no-op, 사용자 실행 PREP/runtime integration을 별도 TARGET 재검증해야 한다.
