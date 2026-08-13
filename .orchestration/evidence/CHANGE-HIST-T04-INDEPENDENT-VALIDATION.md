# CHANGE-HIST-T04 독립 검증 증거

## 판정

- 최종 판정: `FAIL`
- 차단 상태: `BLOCKED_BY_INITIAL_CHECKPOINT_AND_CONTENT_TYPE_FENCE`
- exact candidate SHA: `a52eb4f6f66ae315d7a73ee703f04eaa3326bd63`
- product SHA: `5cc3652cdc82d2a033edd95003e0f5f6525c7e0e`
- 비교 base SHA: `9fb7deaa88dfd03d6604ecfd5e86b3c8a8c69a83`
- 검증일: 2026-08-14 (KST)
- 검증 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`
- Node 22.19+ 실행: `TARGET_RECHECK_REQUIRED` — 로컬 실행 파일이 없었다.
- 제품 repair: `NOT_EXECUTED` — 독립 검증 계약에 따라 제품, dependency, lockfile, test를 수정하지 않았다.

시작 시 worktree는 clean이었고 HEAD는 exact candidate와 일치했다. base부터 candidate까지의 변경은
builder evidence/receipt 2개와 `frontend/package.json`, `frontend/package-lock.json`,
`frontend/poc-mcl-capture.mjs`, `frontend/poc-mcl-capture.test.mjs`,
`frontend/poc-state-store.mjs`, `frontend/poc-state-store.test.mjs`의 정확히 8개 경로다.

## 차단 발견

### F-01 — 최초/빈 partition의 durable capture boundary가 없어 retention gap을 조용히 건너뛸 수 있음

- 심각도: `HIGH`
- 분류: `FAIL`
- 위치: `frontend/poc-mcl-capture.mjs:167-186`, `frontend/poc-state-store.mjs:601-645`

checkpoint가 없으면 capture는 Kafka `low`를 resume 값으로 사용한다. 그리고 모든 partition이
`next === high`인 빈 window이면 `appendChangeHistoryCapture`를 한 번도 호출하지 않고 성공 결과를
즉시 반환한다. state store의 checkpoint 생성은 오직 실제 source record를 append할 때만 수행되므로,
이 성공 실행은 `low/high` 또는 ADR의 최초 `B[p]`를 PostgreSQL에 남기지 않는다.

공개 API 기반 재현에서 `low=high=100`, stored checkpoint `null`인 실행은
`nextOffset=100`, `processedRecords=0`으로 성공했지만 durable append 호출은 `0`회였다. 그 뒤 Kafka
retention low가 150으로 진행되면 다음 실행도 stored checkpoint가 없으므로 150을 새 시작점으로
채택한다. 즉 100..149 손실 여부를 증명하거나 `HISTORY_GAP`으로 중지할 근거가 사라진다. 또한 fresh
source는 ADR-0123의 고정 end boundary `B[p]`가 아니라 현재 retained low부터 과거 MCL을 읽는다.

이는 ADR-0123의 `capture_boundary`/`B[p]` 기록과 새 partition·retention gap fail-closed 계약
(`docs/adr/0123-datahub-change-history-ledger.md:92-109,128-135`) 및 Task의 durable PostgreSQL
checkpoint canonical-resume 요구를 충족하지 못한다.

최소 repair acceptance는 다음과 같다.

1. consume 전에 모든 고정 partition의 최초 boundary를 PostgreSQL에 원자적으로 영속화하거나,
   이미 영속화된 checkpoint 없이는 capture를 시작하지 않는다.
2. ADR-0123에 따라 fresh activation의 `B[p]` 의미와 `first_exact_offset`을 명시하고, 빈 partition도
   재시작 가능한 durable row를 남긴다.
3. 최초 빈 실행 뒤 retention low 전진, 새 partition 출현, boundary-before-consume 실패를 focused
   negative test로 추가하고 손실 구간은 반드시 fail closed 한다.

### F-02 — GenericAspect `contentType`을 확인하지 않아 알 수 없는 encoding을 수용함

- 심각도: `MEDIUM`
- 분류: `FAIL`
- 위치: `frontend/poc-mcl-capture.mjs:426-446`

`decodeAspectDocument`는 wrapper에 `value`가 있으면 이를 꺼내 JSON parse하지만 `contentType`을 읽거나
검증하지 않는다. 공개 normalization API에 `contentType: application/avro`와 JSON처럼 보이는 bytes를
주입한 재현은 `supported=true`, event 1개로 성공했다. outer Confluent Avro framing을 검증하더라도
GenericAspect의 inner encoding 계약이 바뀌거나 잘못된 경우 fail closed 하지 않는다.

최소 repair acceptance는 DataHub v1.6에서 승인한 정확한 GenericAspect JSON content type만 허용하고,
누락·다른 content type은 해당 offset 앞에서 실패시키는 것이다. 실제 representative wrapper의 정상
case와 missing/unknown/non-JSON content type negative test가 함께 필요하다.

## 계약별 검증 결과

| 항목 | 결과 | 독립 증거 |
|---|---|---|
| exact direct dependency/lock | `PASS` | root와 lock resolved version이 `kafkajs@2.2.4`, `@kafkajs/confluent-schema-registry@4.1.0`으로 일치하고 integrity 누락이 없다. |
| pure-JS/native | `PASS_WITH_TARGET_RECHECK` | lock 추가 20 package에 `os/cpu/libc/gypfile` 없음, 추가 dependency subtree의 `.node/.so/.dylib/.dll` 없음. `protobufjs`의 JS postinstall은 존재하며 Linux AMD64 offline artifact 재검증은 열려 있다. |
| license scope | `PASS_WITH_TARGET_RECHECK` | KafkaJS MIT, transitive MIT/BSD-3-Clause/Apache-2.0을 확인했다. registry manifest license field는 비어 있고 배포 LICENSE는 MIT text이므로 builder의 제한적 표현이 정확하다. |
| config/secret/log boundary | `PASS` | broker/client/group/topic/source/schema/provider/auth/TLS flag/limit은 config 또는 environment 입력이며 추가 product line의 credential/local-endpoint/conflict-marker scan hit가 없다. KafkaJS log level은 `NOTHING`이다. |
| fixed high watermark/bounded count | `PASS` | admin high를 consumer 시작 전에 고정하고 partition window 합계를 `maxMessages`로 제한한다. |
| durable checkpoint/retention gap | `FAIL` | F-01. existing checkpoint가 low보다 뒤면 거부하지만 최초/빈 boundary가 영속화되지 않는다. |
| Kafka subscribe/run/seek ordering | `PASS_STATIC_ONLY` | KafkaJS 2.2.4 source에서 group assignment 완료 후 동기 `GROUP_JOIN` event가 fetch보다 먼저 발생하고 listener가 pending partition을 DB checkpoint로 seek한다. 실제 broker/rebalance는 미실행이다. |
| malformed supported record/DB failure | `PASS` | focused test가 malformed JSON과 DB 실패 시 checkpoint no-advance를 확인했다. |
| unsupported aspect zero-event ack | `PASS` | body를 열지 않고 zero-event append와 checkpoint advance를 같은 transaction에서 수행한다. |
| Confluent frame/v1.6 wrapper | `FAIL` | magic byte/schema id Avro decode와 representative GenericAspect value는 통과하지만 F-02의 inner content-type fence가 없다. |
| supported aspect/category/fan-out/bounds | `PASS_STATIC` | 6개 aspect allowlist, 2개 intermediate category, 기존 5개 storage category, 최대 1000 events/16 KiB document와 schema field fan-out을 확인했다. |
| replay/dedup/restart | `PASS_FOCUSED` | source/topic/partition/offset identity, canonical sort/ordinal, conflict hash와 restart-from-DB focused test가 통과했다. |
| T03N 및 POC 회귀 | `PASS` | focused state-store test, 전체 ESLint, POC build와 build 후 server 28/28이 통과했다. |

## 실행 결과

- `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs`: `PASS 10/10`
- `npm run lint`: `PASS`
- `npm run build:poc`: `PASS`; 기존 500 kB chunk warning만 존재
- build 완료 후 `npm run test:poc-server`: `PASS 28/28`
- build와 동시에 실행한 최초 server regression: `27/28`; build가 `dist-poc`을 교체하던 중 root만
  `404 != 200`이었고, 동일 candidate를 build 후 단독 재실행해 28/28 PASS로 분리 확인
- F-01 empty-window 공개 API 재현: 성공 결과지만 durable append `0`, consumer 생성 `0`
- F-02 content-type 공개 API 재현: `application/avro`가 `supported=true`, event `1`로 수용됨
- `git diff --check base..candidate`: `PASS`
- 변경 경로 allowlist, conflict marker, 추가 product line secret/local-endpoint scan: `PASS`
- lock structural scan: direct exact pin/resolved version 일치, 추가 package `20`, integrity 누락 `0`,
  platform/native metadata `0`; package-lock SHA-256은
  `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`
- 임시 symlink 환경의 `npm ls --all`은 npm이 링크 대상 tree를 validation project의 extraneous/missing으로
  분류해 `ELSPROBLEMS`를 반환했으므로 lock 판정 근거로 사용하지 않았다. 설치 없이 lock 구조, 실제
  resolved manifests, focused 실행으로 교차검증했다.

builder worktree의 exact `frontend/node_modules`는 명세대로 validation worktree에 임시 symlink로만
사용했고, 증거 작성 전에 링크를 제거했다.

## NOT_EXECUTED 및 경계

- Node 22.19+ 및 Linux AMD64 offline npm artifact/checksum/SBOM/license: `TARGET_RECHECK_REQUIRED`
- live Kafka/MCL/Schema Registry, 실제 rebalance/partition topology/retention/catch-up: `NOT_EXECUTED`
- live PostgreSQL DDL/transaction/concurrency 및 active POC runtime: `NOT_EXECUTED`
- dependency install/change, 제품·test·package·lock repair: `NOT_EXECUTED`
- provider/container/DB mutation, `datariver_v1`, merge, push, PREP, OPS: `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 결론

dependency pin, bounded decode, atomic per-record append, focused/회귀 테스트의 나머지 항목은 통과했다.
그러나 F-01은 최초 durable boundary 없이 history loss를 조용히 건너뛸 수 있고, F-02는 inner aspect
encoding 변경을 fail closed 하지 않는다. 두 repair와 fresh independent revalidation 전에는 candidate를
G1 후보로 승인할 수 없다.
