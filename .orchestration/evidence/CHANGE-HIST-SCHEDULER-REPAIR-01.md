# CHANGE-HIST-SCHEDULER-REPAIR-01 수정 증적

## 범위와 provenance

- Task: `CHANGE-HIST-SCHEDULER-REPAIR-01`
- finding: `F-01 HIGH` scheduler monotonic boundary regression
- exact base SHA: `a937b1b1da04df8edc0bda3b0b37911e1660bc9c`
- product commit: `2b6d8bf7d5b4190e648be5ee38b781ac9e335241`
- 실제 검증 런타임: Node `v25.9.0`, npm `11.12.1`
- 제품 변경 경로: `frontend/poc-state-store.mjs`, `frontend/poc-state-store.test.mjs`
- package/lock SHA-256: `f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`, `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`
- dependency/framework/service/container/config/UI/CR/Python 변경: 없음
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

시작 시 실제 HEAD는 exact base와 일치했고 worktree는 clean이었다. `node_modules`가 없어 사전 승인된
`npm ci --ignore-scripts`로 기존 exact lockfile만 설치했으며 package/lock은 변경하지 않았다. 제품
커밋은 허용된 두 frontend 경로만 포함한다.

## F-01 수정 내용

기존 `runChangeHistoryScheduler`의 session advisory lock 이름과
`change-history-scheduler-v1:<lockName>` scope를 그대로 유지했다. lock 획득 뒤 저장된 receipt가 있으면
`last_successful_schedule`을 JavaScript `Date`가 읽을 수 있고 `toISOString()`과 입력이 정확히 같은
명시적 UTC timestamp로 검증한다. 누락·비정규·비-UTC 값은 ordered task나 receipt query 전에 예외로
종료한다.

- 저장 경계와 요청 경계가 같으면 기존 `already_completed`를 반환한다.
- 저장 경계가 요청보다 최신이면 `{ status: 'stale', scheduledFor }`만 반환한다. ordered MCL/T05 task와
  receipt write를 호출하지 않고 저장 receipt 값이나 secret을 결과에 포함하지 않는다.
- 요청이 저장 경계보다 최신일 때만 기존 ordered task를 실행한다.
- PostgreSQL upsert는 읽은 이전 경계와 현재 row 경계가 같은지 확인하는 compare 조건과
  `current::timestamptz < requested::timestamptz` 조건을 함께 사용한다. 따라서 충돌 row는 strictly newer
  요청만 갱신한다.
- upsert의 `RETURNING last_successful_schedule` 결과가 정확히 한 행이고 요청 경계와 같은지 확인한다.
  조건부 no-write 또는 불일치이면 성공을 반환하지 않고 fail closed한다.

기존 lock scope, MCL→T05 task 순서, task/receipt failure 의미, disabled 동작과 scheduler module은
변경하지 않았다.

## 회귀 검증

state-store PostgreSQL double 회귀는 다음 순서를 한 lock namespace에서 검증한다.

1. newer `2026-08-13T15:00:00.000Z` 성공
2. older manual `2026-08-12T15:00:00.000Z` 요청
3. newer 경계 exact replay

관찰 결과 ordered task는 총 1회 실행되고 older 요청은 typed `stale`, exact replay는
`already_completed`였다. older와 replay 모두 receipt query 수를 늘리지 않았고 최종 저장 경계는
newer 값으로 유지됐다. 추가로 저장 값 `2026-08-13T15:00:00Z`처럼 유효 시각이지만 exact canonical UTC
형식이 아닌 경우 task/write 전 fail closed하고 unlock/release하는 것을 검증했다. 조건부 upsert가 0행을
반환하는 경우 성공으로 보고하지 않는 회귀도 포함했다. 기존 ordered task 실패, receipt query 실패,
advisory unlock/release 검증은 계속 통과한다.

## 필수 순차 검증 결과

아래 명령은 구현 완료 후 한 프로세스씩 지정 순서로 실행했다.

| 순서 | 명령 | 결과 |
|---:|---|---|
| 1 | `node --test poc-change-history-scheduler.test.mjs poc-state-store.test.mjs` | `PASS`, 13/13 |
| 2 | `npm run lint` | `PASS`, zero warning |
| 3 | `npm run build:poc` | `PASS`; 기존 500 kB chunk-size warning만 관찰 |
| 4 | `npm run test:poc-server` | `PASS`, 28/28 |

`git diff --check`도 통과했고 제품 커밋 직후 worktree는 clean이었다.

## NOT_EXECUTED와 잔여 gate

- Node 22 / TARGET Linux·AMD64: `NOT_EXECUTED`
- 실제 PostgreSQL 다중 session contention 및 live DB conditional upsert: `NOT_EXECUTED`
- 실제 Kafka, Schema Registry, DataHub 연동: `NOT_EXECUTED`
- 배포, 서비스·container 기동/변경, PREP, OPS: `NOT_EXECUTED`
- push, merge, G1-G4 승인: `NOT_EXECUTED`

이 증적은 local source/double 검증 결과만 기록하며 TARGET 또는 운영 준비 완료를 주장하지 않는다.
