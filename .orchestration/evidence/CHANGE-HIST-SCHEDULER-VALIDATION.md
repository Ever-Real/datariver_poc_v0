# CHANGE-HIST-SCHEDULER 독립 검증 증거

## 판정과 provenance

- 최종 판정: `FAIL`
- blocking finding: `F-01 HIGH` 1건
- task / dispatch: `task_7b03b7badbf0` / `ctx_08ed583ec2fd`
- owner role: `50_QUALITY_VALIDATION`
- exact base SHA: `4eb9ce95ec45515f5954350b27abf2874c0dd9da`
- product commit: `660d551059e007850ad41ab2773753fe468cf58c`
- evidence head: `04b7eed0612cbe81efe6c56bebfe4a6e57f55815`
- 검증 환경: macOS arm64, Node `v25.9.0`, npm `11.12.1`
- 제품 repair: `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

검증 시작 시 worktree는 clean이었고 HEAD는 exact evidence head와 일치했다. 제품 commit은 exact
base의 직접 자식이며, evidence head는 제품 commit 뒤의 문서 전용 두 commit을 포함한다. 제품 diff는
아래 여섯 경로뿐이고 제품 뒤 evidence diff는 기존 scheduler evidence/receipt 두 경로뿐이므로
product/evidence 경계가 분리되어 있다.

- `deploy/poc/.env.example`
- `frontend/poc-change-history-scheduler.mjs`
- `frontend/poc-change-history-scheduler.test.mjs`
- `frontend/poc-server.mjs`
- `frontend/poc-state-store.mjs`
- `frontend/poc-state-store.test.mjs`

`frontend/package.json`과 `frontend/package-lock.json`은 제품 diff에 없고 검증 전후 해시는 각각
`f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`,
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`로 동일하다. 새 dependency,
framework, service, container, Python, UI 또는 CR 상태 변경은 없다. `node_modules`가 없어 사전 승인된
`npm ci --ignore-scripts`로 exact lockfile 설치만 수행했으며 package/lock은 변경하지 않았다.

## F-01 HIGH — 오래된 수동 경계가 최신 성공 경계를 퇴행시킴

### 정확한 근거

`frontend/poc-state-store.mjs:930-947`은 advisory lock을 얻은 뒤 저장된
`last_successful_schedule`이 요청 `scheduledFor`와 **정확히 같은 경우만** `already_completed`로
건너뛴다. 저장 경계가 요청보다 최신인지 비교하는 monotonic/fence 조건이 없고, 이후 upsert는 요청
경계를 무조건 `last_successful_schedule`로 덮어쓴다.

tracked 파일을 만들지 않은 in-memory PostgreSQL double probe에서 동일 lock namespace에 다음 순서로
실행했다.

1. newer manual boundary `2026-08-13T15:00:00.000Z` 실행
2. older manual boundary `2026-08-12T15:00:00.000Z` 실행

관찰 결과는 다음과 같다.

- 첫 호출: `succeeded`
- 두 번째 호출: `succeeded`
- ordered task 호출: 2회
- 최종 `last_successful_schedule`: `2026-08-12T15:00:00.000Z`
- advisory unlock / client release: 각 2회
- probe marker: `REPRODUCED_MONOTONIC_REGRESSION`

즉 session advisory lock은 동시 실행만 직렬화할 뿐 실행 경계의 시간 순서를 fence하지 않는다. 오래된
수동 요청이 최신 성공 receipt를 퇴행시키고 ordered capture/reconciliation을 다시 수행하므로, Task의
“stale/older manual boundary cannot regress latest successful boundary” 및 replay/multiple-process 의미를
충족하지 못한다. 따라서 다른 local gate가 통과해도 전체 판정은 `FAIL`이다.

### 최소 repair 계약

- advisory lock 보유 중 저장된 경계를 explicit UTC instant로 검증하고, 저장 경계가 요청 경계보다
  같거나 최신이면 ordered task와 receipt write를 수행하지 않는 typed no-op 결과를 반환한다.
- receipt upsert 자체에도 기존 값보다 더 최신인 경계만 갱신할 수 있는 PostgreSQL 조건을 두어
  monotonic compare/write를 데이터베이스에서 보장한다.
- newer success 뒤 older manual 요청, exact replay, 서로 다른 프로세스의 직렬 경쟁을 검증하고 최종
  receipt가 newer에 고정됨을 회귀 테스트로 증명한다.

제품 소스는 repair하지 않았다.

## 계약 검토와 supplemental 결과

- scheduler disabled 또는 MCL 필수 설정 누락은 inert이며 MCL 모듈은 enabled일 때만 dynamic import한다.
- 기본 `Asia/Seoul` 자정은 KST `00:00`/UTC 전일 `15:00`으로 계산되고, IANA zone의 DST 다음 경계는
  fixed offset 없이 계산된다.
- enabled 상태에서 PostgreSQL 미설정은 scheduler 생성 단계에서 fail-safe한다. disabled 상태는
  PostgreSQL 없이 기존 동작을 유지한다.
- bounded T04 MCL capture 뒤 기존 T05 `startDatahubInventoryRefresh()`를 호출하고 그 뒤 receipt를 쓴다.
- lock unavailable은 task/receipt 없이 `locked`를 반환하고 client를 release했다.
- capture failure, reconciliation failure, receipt failure는 성공 receipt를 남기지 않았다.
- active run 중 stop은 해당 run 완료를 기다렸고 concurrent in-process trigger는 하나의 active promise로
  합쳐졌다.
- deployment-specific Kafka broker/topic/Schema Registry/credential은 환경 변수로만 바인딩되고 새 secret
  literal이나 credential logging, 브라우저 mutation endpoint, UI 경로 또는 CR state mutation은 제품
  diff에서 확인되지 않았다.
- timer는 최소 1 ms와 최대 delay cap을 사용하고 다음 IANA day boundary를 재계산한다.

위 supplemental 결과는 local double/정적 검토 범위이며 F-01을 상쇄하지 않는다. coordinator 지시에
따라 F-01 확정 뒤 추가 supplemental probe는 중단했다.

## 필수 순차 검증

아래 네 검증은 한 프로세스씩 순차 실행했고 결합 실행 전체가 exit success였다.

| 검증 | 결과 |
|---|---|
| `node --test poc-change-history-scheduler.test.mjs poc-state-store.test.mjs` | `PASS`, 12/12 |
| `npm run lint` | `PASS`, zero warning |
| `npm run build:poc` | `PASS`, 기존 500 kB chunk warning만 존재 |
| `npm run test:poc-server` | `PASS`, 28/28 |

실제 검증 런타임은 Node `v25.9.0`이며 Node 22/TARGET로 주장하지 않는다.

## NOT_EXECUTED와 잔여 gate

- 제품 runtime 배포 및 active POC process 기동/재시작: `NOT_EXECUTED`
- 실제 PostgreSQL 다중 process/session lock 경쟁과 장애 주입: `NOT_EXECUTED`
- 실제 Kafka, Schema Registry, DataHub 연동 capture/reconciliation: `NOT_EXECUTED`
- Node 22 및 TARGET Linux/AMD64: `NOT_EXECUTED`
- provider/container/DB mutation, dependency 변경, 제품 repair: `NOT_EXECUTED`
- merge, push, PREP, OPS 및 G1-G4 승인: `NOT_EXECUTED`

## 결론

focused test, lint, build, server regression과 제한된 supplemental 계약은 통과했다. 그러나 최신 성공 뒤
오래된 manual boundary가 ordered work를 다시 실행하고 canonical receipt를 과거로 덮어쓰는 HIGH
monotonicity 결함이 직접 재현되었다. correctness gate를 충족하지 못하므로 exact product commit에 대한
독립 판정은 `FAIL`이다.
