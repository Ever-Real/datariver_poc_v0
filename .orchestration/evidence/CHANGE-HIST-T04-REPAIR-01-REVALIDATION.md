# CHANGE-HIST-T04 REPAIR-01 fresh 독립 재검증 증거

## 판정

- 최종 판정: `PASS`
- 상태: `LOCALLY_REVALIDATED_TARGET_RECHECK_REQUIRED`
- exact candidate SHA: `57a47f86d801b4be68803ef42c15e7a2b0cad1f6`
- product SHA: `79497a5900fed05b80f681af7f14fcb0fddf0845`
- repair base SHA: `d3df8b29d83a0c324dc9b806e8d9506b141c162a`
- 검증일: 2026-08-14 (KST)
- 검증 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`
- 제품 repair: `NOT_EXECUTED`
- blocking finding: 없음

시작 시 worktree는 clean이었고 HEAD는 exact candidate와 일치했다. repair product commit의 변경은
`frontend/poc-mcl-capture.mjs`, `frontend/poc-mcl-capture.test.mjs`,
`frontend/poc-state-store.mjs`, `frontend/poc-state-store.test.mjs`의 네 경로뿐이다.
`package.json`과 `package-lock.json`은 repair base 대비 변경되지 않았으며 lock SHA-256은
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`다.

## F-01 재검증 — durable boundary, concurrency, topology

### 최초 boundary 및 transaction

`runBoundedCapture`는 admin이 반환한 전체 partition inventory를 정렬·중복 검증하고, 각 partition의
고정 high watermark `B[p]`를 `initializeChangeHistoryCaptureBoundaries`에 한 번 전달한다. 이 호출이
성공해 전체 durable checkpoint vector를 반환하기 전에는 consumer를 생성하지 않는다
(`frontend/poc-mcl-capture.mjs:158-209`). `low == high`인 partition도 같은 vector에 포함되며 최초
source/topic에는 `first_exact_offset = next_offset = B[p]`가 기록된다.

state store는 다음 순서의 단일 PostgreSQL transaction을 사용한다
(`frontend/poc-state-store.mjs:601-680`).

1. source identity row를 `INSERT ... ON CONFLICT DO NOTHING`으로 확보한다.
2. 그 source row를 `SELECT ... FOR UPDATE`로 잠가 같은 source의 최초 boundary 초기화를 직렬화한다.
3. 동일 source/topic의 전체 checkpoint row를 정렬해 `FOR UPDATE`로 읽는다.
4. 저장 row가 없을 때만 전체 partition vector를 insert하고, 부분 실패는 source row와 checkpoint
   row를 함께 rollback한다.
5. 저장 row가 있으면 broker partition 집합과 정확히 같은지 비교하고 기존 `next_offset`만 반환한다.

동시 최초 호출에서는 유일 source key의 `INSERT ... ON CONFLICT` 경쟁 뒤 source row lock이 직렬화
지점을 제공한다. 따라서 승자 transaction이 전체 vector를 commit하기 전에는 후속 호출이 그 상태를
기반으로 진행할 수 없다. 기존 source row, 같은 source의 다른 topic, append와의 경쟁도 source row
lock/FK 및 checkpoint row lock 순서로 serialize된다. 이는 SQL 의미에 대한 정적 검증이며 실제
PostgreSQL 두 connection 경쟁 실행은 runtime mutation 금지 때문에 `NOT_EXECUTED`다.

### topology와 inventory fail-closed

- broker inventory가 빈 배열이면 boundary/consumer 전에 `no readable partition inventory`로 중지한다.
- broker inventory에 같은 partition이 두 번 있으면 boundary/consumer 전에 중지한다.
- 저장 vector 대비 새 partition 또는 사라진 partition은 길이/정렬 집합 불일치로 rollback한다.
- 저장 `next_offset < low`는 `HISTORY_GAP`, `next_offset > captured high`는 invalid checkpoint로
  consumer 전에 중지한다.
- Kafka offset과 DB bigint를 JS `Number`로 바꿀 때 `Number.isSafeInteger`를 강제한다. 따라서
  `2^53` 이상의 offset은 정밀도 손실로 진행하지 않고 consumer 전에 fail closed한다. 이는 장기
  portability 한계이며 silent skip은 아니다.

focused test는 fresh non-empty/empty partition, retention low 전진, new/missing topology, boundary
failure rollback 및 duplicate/concurrent 호출을 통과했다. 보충 공개 API probe는 empty inventory,
duplicate inventory, unsafe high offset에서 consumer 생성 없이 fail closed함을 확인했다.

### transaction-double fidelity

state-store test double은 BEGIN 시 네 in-memory collection을 snapshot하고 ROLLBACK 시 모두 복구하므로
부분 checkpoint insert 실패 후 source/checkpoint row가 남지 않는 atomicity assertion에는 충실하다.
그러나 같은 client와 공유 snapshot을 사용하고 실제 row lock/blocking/isolation을 구현하지 않으므로
`Promise.all` test 자체는 PostgreSQL lock 경쟁의 독립 증명이 아니다. 동시성 판정은 위 실제 SQL의
source `FOR UPDATE`, unique conflict 및 transaction ordering을 직접 검토한 결과이며, target에서는
실제 PostgreSQL multi-connection 재검증이 필요하다.

## F-02 재검증 — GenericAspect content type

지원 aspect의 모든 non-null `aspect`와 `previousAspectValue`는 object wrapper, own `value`, 정확한
`contentType: application/json`을 모두 만족해야 bounded JSON decode로 진행한다
(`frontend/poc-mcl-capture.mjs:447-470`). 누락, `application/avro`, `text/plain`, invalid JSON은
`appendChangeHistoryCapture` 전 normalize 단계에서 중지한다. null previous wrapper는 정상적으로
허용된다.

기존 focused test의 current `aspect` valid/missing/unknown/non-JSON 계약에 더해 보충 probe로
`previousAspectValue`의 missing/`application/avro`/`text/plain`을 모두 fail-closed 확인했다. getter가
호출되면 실패하도록 만든 unsupported aspect의 `aspect`/`previousAspectValue`는 열리지 않았고
zero-event 결과를 반환했다.

## 실행 결과

| 검증 | 결과 |
|---|---|
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | `PASS 13/13` |
| 보충 공개 API probe | `PASS`: empty inventory, unsafe offset, duplicate topology, previous wrapper content type, unsupported body unopened |
| `npm run lint` | `PASS`, 전체 frontend ESLint |
| `npm run build:poc` | `PASS`, 기존 500 kB chunk warning만 존재 |
| build 후 `npm run test:poc-server` | `PASS 28/28` |
| repair product diff allowlist | `PASS`, 정확히 네 product/test 경로 |
| package/lock unchanged 및 lock hash | `PASS` |
| `git diff --check`, conflict marker, 추가 endpoint/credential pattern scan | `PASS` |
| 임시 `frontend/node_modules` symlink 제거 | `PASS` |

첫 보충 probe 실행은 제품 실패가 아니라 예상 오류문구 정규식이 실제 `is not` 대신 `must be`를
기대해 assertion 1건이 실패했다. 이 실행에서 focused `13/13`은 이미 통과했지만 lint/build/server는
시작되지 않았다. 또한 `cd frontend` 이후 상대 trap 경로가 어긋나 남은 symlink를 정확한 절대경로로
즉시 제거했다. 정규식과 trap을 바로잡은 새 실행에서 보충 probe, lint, build, server, diff/package
검사를 모두 통과했고 최종 symlink 부재를 별도로 확인했다.

## NOT_EXECUTED 및 잔여 gate

- 실제 Kafka/MCL/Schema Registry, rebalance, retention/catch-up 및 live empty-topic 관찰:
  `NOT_EXECUTED`
- 실제 PostgreSQL multi-connection concurrency, isolation, rollback과 active POC DB/runtime:
  `NOT_EXECUTED`
- Node `22.19+` exact 및 Linux AMD64 offline npm artifact/checksum/SBOM/license:
  `TARGET_RECHECK_REQUIRED`
- provider/container/DB mutation, dependency install/change, 제품·test·package·lock repair:
  `NOT_EXECUTED`
- `datariver_v1`, merge, push, PREP, OPS: `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 결론

F-01의 최초 전체 partition boundary 원자적 영속화와 retention/topology fail-closed, F-02의 정확한
GenericAspect JSON content type fence가 candidate에서 충족된다. 로컬 정적·focused·회귀 범위의
blocking finding은 없으므로 `PASS`다. 이 판정은 live target 또는 G1-G4 승인이 아니며, 실제
PostgreSQL/Kafka와 Node 22/Linux 환경의 재검증은 계속 열려 있다.
