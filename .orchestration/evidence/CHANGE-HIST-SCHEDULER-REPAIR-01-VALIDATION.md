# CHANGE-HIST-SCHEDULER-REPAIR-01 독립 검증 증적

## 판정

- Task: `task_4e5aea31a283`
- 역할: `50_QUALITY_VALIDATION`
- 판정: `PASS`
- 검증 대상 HEAD: `bc59cd2051d96cb306d401fb7ce37a1287275e2d`
- 비교 범위: `a937b1b1da04df8edc0bda3b0b37911e1660bc9c..bc59cd2051d96cb306d401fb7ce37a1287275e2d`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

이 판정은 지정 worktree의 소스 정적 검토와 로컬 double 기반 자동 검증에 한정한다. 검증 중 소스
repair는 수행하지 않았고, 허용된 이 증적과 receipt만 작성했다.

## 시작 조건과 범위

지정 worktree는
`/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-scheduler-repair-01-validation`이다.
시작 시 `git rev-parse HEAD`는 위 exact HEAD와 일치했고 `git status --short`는 출력이 없어 clean이었다.

비교 범위에는 다음 두 커밋과 네 파일만 있다.

- `2b6d8bf7d5b4190e648be5ee38b781ac9e335241` — 제품 소스와 회귀 테스트
- `bc59cd2051d96cb306d401fb7ce37a1287275e2d` — 기존 repair evidence/receipt
- 제품 변경: `frontend/poc-state-store.mjs`, `frontend/poc-state-store.test.mjs`
- 기존 문서 추가: `.orchestration/evidence/CHANGE-HIST-SCHEDULER-REPAIR-01.md`,
  `.orchestration/receipts/CHANGE-HIST-SCHEDULER-REPAIR-01.md`

package/dependency/config/service/container/UI/CR/Python 변경은 비교 범위에 없었다.

## F-01 정적 독립 검토

`frontend/poc-state-store.mjs`의 변경을 기준으로 다음을 확인했다.

1. 저장된 `last_successful_schedule`은 task 실행 전에 `Date` 해석 가능 여부뿐 아니라
   `toISOString()`과 원문 일치까지 확인하므로 exact canonical UTC만 허용한다.
2. 저장 경계와 요청 경계가 같으면 `already_completed`를 반환하고 task와 receipt write를 실행하지
   않는다.
3. 저장 경계가 요청보다 최신이면 요청 `scheduledFor`만 포함한 `stale`을 반환한다. 이 경로는 task와
   receipt write를 실행하지 않고 저장 receipt나 secret을 반환하지 않는다.
4. malformed 또는 비정규 저장 경계는 task와 write 전에 예외로 fail closed하며 advisory unlock과
   client release는 `finally`에서 유지된다.
5. PostgreSQL upsert는 읽은 이전 경계와 현재 row 경계의 동등 비교와
   `current::timestamptz < requested::timestamptz`를 함께 요구한다. `RETURNING`이 정확히 한 행이며 반환
   경계가 요청 경계와 같을 때만 성공하므로 조건 불충족/경쟁 갱신을 성공으로 오인하지 않는다.
6. 기존 session advisory lock key/scope, 입력 trigger allowlist, ordered task 실패 및 receipt 실패 전파,
   disabled scheduler 동작은 약화되지 않았다.

`git diff --check a937b1b..bc59cd2`는 통과했다. 제품 diff 추가 행에서 test skip/only,
`eslint-disable`, `@ts-ignore`, TODO/FIXME, 환경 기반 우회, 상수 true/무조건 성공과 같은 hardcoding 또는
guard 우회 표식은 발견되지 않았다. 테스트의 고정 UTC 값과 lock 이름은 경계 순서를 재현하기 위한
결정적 fixture이며 제품 우회가 아니다.

## 설치 및 런타임

- 실제 런타임: Node `v25.9.0`, npm `11.12.1`
- `frontend/node_modules`가 없어 `npm ci --ignore-scripts`를 exact lockfile로 1회 실행: `PASS`
- 설치 전후 `frontend/package.json` SHA-256:
  `f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`
- 설치 전후 `frontend/package-lock.json` SHA-256:
  `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`
- 설치 후 두 파일에 대한 `git status --short` 출력 없음: package/lock unchanged

## 필수 순차 실행 결과

아래 명령은 한 프로세스씩 표시 순서대로 실행했다.

| 순서 | 명령 | 결과 |
|---:|---|---|
| 1 | `node --test poc-change-history-scheduler.test.mjs poc-state-store.test.mjs` | `PASS`, 13/13, fail/skipped/todo 0 |
| 2 | `npm run lint` | `PASS`, `eslint . --max-warnings=0`, 경고/오류 없음 |
| 3 | `npm run build:poc` | `PASS`; Vite 2145 modules, 기존 500 kB 초과 chunk 경고만 관찰 |
| 4 | `npm run test:poc-server` | `PASS`, 28/28, fail/skipped/todo 0 |

focused state-store 회귀는 newer 성공 뒤 older manual 요청이 `stale`이고 task/write를 추가 호출하지
않으며 저장 경계가 퇴행하지 않는 것을 확인한다. 이어지는 exact replay는 `already_completed`이고 전체
task 호출 수는 1회다. malformed 저장 경계는 task/write 전에 거부되고 conditional upsert 0행은
성공으로 보고되지 않는다. scheduler focused 테스트는 MCL→T05→receipt 순서와 manual boundary guard를
함께 확인한다.

## 명시적 미실행과 승인 경계

- Node 22: `NOT_EXECUTED`
- 실제 PostgreSQL 다중 session contention 및 live DB compare/write: `NOT_EXECUTED`
- 실제 Kafka, Schema Registry, DataHub 연동: `NOT_EXECUTED`
- TARGET Linux/AMD64: `NOT_EXECUTED`
- 서비스/container 기동 또는 변경, 배포, PREP, OPS: `NOT_EXECUTED`
- push, merge: `NOT_EXECUTED`
- G1/G2/G3/G4 승인: `NOT_APPROVED`

따라서 `PASS`는 로컬 독립 검증 범위의 F-01 repair 판정이며, TARGET/운영 준비나 gate 승인을 의미하지
않는다.
