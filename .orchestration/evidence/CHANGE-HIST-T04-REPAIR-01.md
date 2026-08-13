# CHANGE-HIST-T04 REPAIR-01 evidence

- 상태: `REPAIRED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`
- 검증일: 2026-08-14 (KST)
- exact base: `d3df8b29d83a0c324dc9b806e8d9506b141c162a`
- product commit: `79497a5900fed05b80f681af7f14fcb0fddf0845`
- 브랜치/worktree: `Ever-Real/change-hist-t04-repair-01` /
  `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t04-repair-01`
- 검증 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`
- 수정 범위: 독립 검증의 `F-01`, `F-02`만 수리
- architecture deviation: 없음

## F-01 — 최초 durable capture boundary

`poc-mcl-capture.mjs`는 Kafka partition inventory와 각 partition의 고정 high watermark `B[p]`를
읽은 직후, consumer 생성 전에 단일 `initializeChangeHistoryCaptureBoundaries` 호출로 전체 boundary
vector를 PostgreSQL에 전달한다. 최초 source/topic은 `first_exact_offset = next_offset = B[p]`로 모든
partition을 같은 transaction에서 기록한다. `low == high`인 빈 partition과 retained record가 있는
partition 모두 동일하게 boundary row를 남기며, `B[p]` 이전 retained history를 guaranteed-forward
MCL로 소비하지 않는다.

state store는 기존 source identity row를 `FOR UPDATE`로 잠가 boundary 초기화를 직렬화한다. 이미
초기화된 source/topic은 저장된 partition 집합과 broker inventory가 정확히 같을 때만 기존
`next_offset`을 반환한다. 새 partition, 사라진 partition, 중복 inventory는 fail closed하며, 기존
checkpoint가 Kafka low보다 뒤면 `HISTORY_GAP`, captured high보다 앞서면 invalid checkpoint로
중단한다. boundary transaction 중 하나라도 실패하면 rollback되고 consumer는 생성되지 않는다.

focused negative/positive contract는 다음을 확인했다.

- 최초 non-empty 두 partition이 각각 현재 high `2`, `1`에 영속화되고 record consumer는 생성되지 않음
- 최초 empty partition의 `B[p]=100`이 durable row로 남음
- 같은 boundary의 동시/중복 초기화가 같은 결과를 반환하고 partition row를 중복 생성하지 않음
- 최초 empty 실행 뒤 retention low가 `150`으로 전진하면 저장된 `100`과 비교해 fail closed
- 새 partition과 broker에서 사라진 durable partition 모두 topology change로 fail closed
- boundary DB failure 시 consumer 생성 `0`, source/checkpoint partial row `0`, transaction rollback

## F-02 — GenericAspect content type fence

지원 aspect의 모든 non-null `aspect`/`previousAspectValue`는 DataHub GenericAspect wrapper와 정확한
`contentType: application/json`을 가져야 한다. wrapper 또는 content type이 없거나
`application/avro`, `text/plain` 등 다른 값이면 bounded JSON parse 전에 실패한다. 실제 representative
Avro wrapper의 `application/json` 정상 case는 유지된다. Unsupported aspect는 기존과 같이 body를 열지
않고 zero-event transaction으로 offset을 인정하므로 이 fence가 unsupported payload를 새로 해석하지
않는다.

## 변경 경로

- `frontend/poc-mcl-capture.mjs`
- `frontend/poc-mcl-capture.test.mjs`
- `frontend/poc-state-store.mjs`
- `frontend/poc-state-store.test.mjs`

`frontend/package.json`과 `frontend/package-lock.json`은 변경하지 않았다. lock SHA-256은 기존과 같은
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`다.

## 실행 검증

| 명령 | 결과 |
|---|---|
| `node --test poc-mcl-capture.test.mjs poc-state-store.test.mjs` | `PASS 13/13` |
| `npm run lint` | `PASS`, 전체 frontend ESLint |
| `npm run build:poc` | `PASS`; 기존 500 kB chunk warning만 존재 |
| `npm run test:poc-server` | `PASS 28/28` |
| `git diff --check` 및 허용 경로 검사 | `PASS` |
| 추가 line secret/local-endpoint 및 conflict marker scan | `PASS`, 발견 없음 |

첫 full validation 시 test double의 `structuredClone`이 ESLint `no-undef` 1건으로 차단되어 build/server는
그 실행에서 시작되지 않았다. test double 복사를 일반 object spread로 바꾼 뒤 focused test부터 전체
순서를 다시 실행해 위 최종 결과를 얻었다. 제품 로직 실패는 아니었다.

검증 동안 기존 builder의 exact `frontend/node_modules`를 임시 untracked symlink로만 사용했고 설치나
dependency 변경은 수행하지 않았다. 최종 검증 종료 trap으로 symlink를 제거했다.

## NOT_EXECUTED / 잔여 gate

- live Kafka/MCL/Schema Registry, 실제 rebalance/partition topology/retention/catch-up:
  `NOT_EXECUTED`
- live PostgreSQL DDL/transaction/concurrency와 active POC runtime/provider/container mutation:
  `NOT_EXECUTED`
- Node `22.19+` exact 및 Linux AMD64 target 재검증: `TARGET_RECHECK_REQUIRED`
- Python, UI, CR, scheduler, 새 service/container/framework, `datariver_v1`: `NOT_EXECUTED`
- merge, push, PREP, OPS: `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

F-01/F-02의 로컬 repair blocker는 없다. 다음 단계는 이 exact evidence candidate에 대한 fresh independent
validation이다.
