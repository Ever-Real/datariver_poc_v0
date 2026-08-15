# MCL-COVERAGE-REPAIR-01 신선 독립 재검증 증적

- **Task / Dispatch:** `MCL-COVERAGE-REPAIR-01-FRESH-REVALIDATION` / `task_0b74c3747d6e` / `ctx_4afd12bb72b4`
- **역할 / 모델:** `50_QUALITY_VALIDATION` / `gpt-5.6-sol High controlled fallback`
- **검증 시작 HEAD:** `91ca594c178169f13270634d876b9e98323e453d` (시작 시 clean)
- **Product SHA:** `4743d29a9e00a103b71f3485cd5baf0ad9cf48d5`
- **Repair base SHA:** `042f8a2e3c066407411f9fd196f5ac4ef18f9972`
- **환경:** Darwin arm64, Node `v25.9.0`, npm `11.12.1`
- **판정:** **FAIL_REPAIR_REQUIRED**
- **PREP 실제 이벤트:** **TARGET_RECHECK_REQUIRED**
- **Product write:** **NONE**

## 차단 finding

### F-02 — committed test의 미사용 destructuring binding이 lint를 차단함

Control Plane이 동일 candidate에서 `npm run lint`를 신선 재현했고 exit `1`로 실패했다. 정확한 위치와 오류는 `frontend/poc-mcl-capture.test.mjs:633:11`, destructuring으로 할당된 `nativeDataType`이 사용되지 않는다는 `no-unused-vars`이다.

```text
frontend/poc-mcl-capture.test.mjs:633:11
nativeDataType is assigned a value but never used  no-unused-vars
```

validator 권한은 `READ_ONLY_PRODUCT / DO_NOT_REPAIR_FINDINGS`이므로 해당 제품 테스트를 수정하지 않았다. 이 blocker 때문에 F-01 parser 동작이 소스·집중 테스트에서 정상이어도 candidate 전체 판정은 PASS가 될 수 없다.

## ancestry와 변경 경계

- ancestry는 `042f8a2e3c066407411f9fd196f5ac4ef18f9972 -> 4743d29a9e00a103b71f3485cd5baf0ad9cf48d5 -> 91ca594c178169f13270634d876b9e98323e453d`의 직계 선형 관계다.
- repair product diff는 정확히 `frontend/poc-mcl-capture.mjs`, `frontend/poc-mcl-capture.test.mjs` 두 파일뿐이다.
- product 이후 `91ca594`는 repair evidence/receipt 두 파일만 추가한 docs-only commit이다.
- product diff에 package/lock 변경, secret, credential, 고정 배포 IP 또는 새 endpoint hardcode는 없다.
- `frontend/package.json` SHA-256은 `d41aa826a203243509e7684eb45a733c7b24a26df0dcf4a0145f05e256d83789`, `frontend/package-lock.json`은 `534d792566f0e9371ca1c7ca7166acbbdcc801f07146450ff54005b188a28be5`이며 `npm ci` 전후 동일하다.

## F-01 계약 재검토

DataHub v1.6 primary PDL은 `SchemaField.type`을 required `SchemaFieldDataType`, `nativeDataType`을 required `string`, `nullable`을 기본값 `false`인 boolean으로 정의한다. `SchemaFieldDataType`의 required outer `type`은 정확히 13개 supported type을 가진 union이다.

- [DataHub v1.6.0 SchemaField.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaField.pdl)
- [DataHub v1.6.0 SchemaFieldDataType.pdl](https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/metadata-models/src/main/pegasus/com/linkedin/schema/SchemaFieldDataType.pdl)

committed GenericAspect JSON fixture는 실제 사용 계약인 `type.type.com.linkedin.schema.NumberType` 두 단계 Rest.li discriminator를 구성한다. 독립 probe도 아래 valid shape를 canonical `NumberType`과 `nullable=false`로 정규화했고, 이전 guessed one-level shape는 거부했다.

```json
{"fieldPath":"id","nativeDataType":"double precision","type":{"type":{"com.linkedin.schema.NumberType":{}}}}
```

parser 정적 검토와 독립 negative probe에서 바깥 object는 own `type` 하나만, inner union은 own supported discriminator 하나만, payload는 plain object만 허용했다. missing/multiple/unknown, `toString`/`constructor`/`__proto__` prototype 이름, null/array payload 및 outer extra member는 fail-closed했고 canonical leaf output은 고정 mapping으로 결정적이다.

`nativeDataType`은 required strict bounded string으로 missing, empty, non-string, 501자, leading/trailing whitespace를 거부하고 internal whitespace는 보존한다. `optionalDocumentString`은 schema summary의 기존 두 호출에만 남아 있으며 unrelated field behavior는 product diff에서 변경되지 않았다. nullable 누락은 PDL 기본값과 같은 `false`다.

## 기존 coverage 확인

committed test와 이미 완료한 focused 실행에서 다음 경계는 유지됐다.

- empty description의 MCL call-site 전용 null canonicalization
- column tag/term ADD·REMOVE 및 logical/native/nullable UPDATE
- field rename의 inferred rename 금지와 exact DELETE+CREATE
- `status.removed` 삭제·재활성화, dataset entity lifecycle, ambiguous initial/UPSERT 무추정
- generation B 삭제 URN의 Search/Tree/Chat exact·vector 제외와 generation C 동일 URN 재노출
- ChangeHistory API의 LIFECYCLE/detail/zero-count 계약과 Monitoring generic filter/detail behavior

## 실행 결과

| 검증 | 결과 |
| --- | --- |
| `npm ci` | PASS — 370 packages, 0 vulnerabilities, lock unchanged |
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | PASS 27/27 |
| 두 단계 valid/one-level·prototype·payload·native boundary 독립 probe | PASS |
| 선행 `npm run build:poc` | PASS — 기존 chunk-size advisory만 출력 |
| `node --test poc-server.test.mjs` | PASS 14/14 (localhost listen 허용 환경의 실효 재실행) |
| `node --test poc-catalog-performance.test.mjs` | PASS 5/5 (localhost listen 허용 환경의 실효 재실행) |
| ChangeHistory API + Monitoring focused Vitest | PASS 2 files / 17 tests |
| `npm run typecheck` | PASS |
| 최종 `npm run build:poc` | PASS — 기존 chunk-size advisory만 출력 |
| `npm run lint` | **FAIL / F-02**, Control Plane exact reproduction, exit 1 |
| `git diff --check`, exact allowlist, package/lock 검사 | PASS |

restricted sandbox에서 localhost listen은 `EPERM`, Vitest config 임시 파일 쓰기는 `EPERM`으로 한 차례 차단됐으며, 허용된 실효 재실행 결과를 위 표에 기록했다. Control Plane의 lint 재현을 받은 즉시 추가 broad validation을 중단했고, 지시대로 `npm test`는 실행하지 않았다.

## Docker / runtime / PREP 경계

- authoritative Node 22/Linux amd64 POC image는 `deploy/poc/Dockerfile.example`이다.
- Docker build는 parser-only repair의 source/test blocker 판정에 필요하지 않아 **NOT_EXECUTED**로 남겼다. `frontend/Dockerfile`도 실행하지 않았다.
- DB/Kafka/DataHub/PREP/OPS mutation, service/container start, push/merge는 수행하지 않았다.
- PREP actual DataHub v1.6 MCL event 검증은 계속 **TARGET_RECHECK_REQUIRED**다.

## 결론

F-01의 DataHub v1.6 parser 계약 자체는 local source와 focused tests에서 폐쇄된 것으로 확인됐지만, F-02 lint blocker가 새로 확정됐다. 따라서 최종 상태는 **FAIL_REPAIR_REQUIRED**이며 product owner가 미사용 binding을 보수한 새 candidate에서 lint와 관련 focused gate를 다시 독립 검증해야 한다.
