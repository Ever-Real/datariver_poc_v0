# CHANGE-HIST-T06A F-01 PostgreSQL 동시성 보수 증거

- 작업: `task_530e80f9912a`
- 역할: `30_IDENTITY_ACCESS repair builder`
- exact base: `4e73807539b43be681a2b96a2e355195c6397883`
- source product commit: `d297369774ca6434263ab3ec2d97dd37bb34c123`
- 범위: `F-01 both-absent PostgreSQL concurrency race`만 보수
- 승인 상태: `G1-G4 NOT_APPROVED`

## 1. 결함과 보수

기존 `writeCoreWithAccessFence`와 `writeChangeHistoryAccess`는 transaction을 시작한 뒤
`poc_state`의 `change-history-access-v1`/`core` row를 `SELECT ... FOR UPDATE`했다. 두 row가 모두
없는 최초 상태에서는 PostgreSQL row lock이 잠글 대상을 만들지 못하므로, 최초 access bootstrap과
일반 core PUT이 동시에 빈 snapshot을 읽고 각각 계속 진행할 수 있었다. 특히 일반 core PUT이 access
authority 부재를 기준으로 값을 계산한 뒤 access transaction보다 늦게 upsert되면, 새로 생긴 authority
projection을 이전 일반 core 값으로 덮을 수 있는 경쟁 구간이었다.

두 write transaction 모두 `BEGIN` 직후, row `SELECT ... FOR UPDATE` 전에 다음과 같은 동일한 stable
key의 transaction-scoped advisory lock을 획득하도록 했다.

`SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, parameter
`change-history-access-v1`(`CHANGE_HISTORY_ACCESS_SCOPE`).

이 lock은 transaction 종료 때 자동 해제되므로 session lock이나 명시적 unlock을 추가하지 않았다.
먼저 획득한 transaction이 종료된 뒤 두 번째 transaction이 row 상태를 다시 읽어, 일반 core write는
authority projection을 보존하고 access CAS는 변경된 version을 stale로 거부한다. 기존 memory 경로,
version 계산, 오류 코드, commit/rollback 및 protected-field semantics는 변경하지 않았다.

## 2. 테스트 보강

기존 PostgreSQL double을 양쪽 row가 없는 상태로 시작하도록 바꾸고 두 write path를 각각 빈 상태에서
실행했다. generic core write와 access bootstrap 모두 다음 순서를 assertion한다.

1. `BEGIN`
2. `pg_advisory_xact_lock`
3. `ORDER BY scope FOR UPDATE`
4. 해당 `INSERT ... ON CONFLICT` write

두 advisory call의 parameter가 동일한 `change-history-access-v1`인지도 확인한다. access bootstrap 뒤
이전 access/core version으로 다시 시도한 stale CAS는 마지막 statement가 `ROLLBACK`인지 확인한다.

## 3. 변경 파일

- `frontend/poc-state-store.mjs`: 두 transaction에 동일 transaction-scoped advisory lock 추가
- `frontend/poc-state-store.test.mjs`: both-absent double의 양 경로 실행 순서와 stale rollback assertion

그 밖의 source, abstraction, dependency, lockfile, configuration, service, UI, schema, T06B는 변경하지
않았다.

## 4. 로컬 실행 증거

exact base/clean 확인 뒤 승인된 `npm ci`를 실행했다. 368 packages 설치, audit 취약점 0건이며
dependency/lockfile 추적 변경은 없었다. 지정 순서의 결과는 다음과 같다.

1. `node --test poc-state-store.test.mjs`: 최종 11 pass, 0 fail
2. `node --test poc-server.test.mjs`: build 전 11 pass, 1 fail. `dist-poc` 미생성 상태라 첫 정적 POC
   응답이 404였고, 나머지 11개 server test는 성공했다.
3. `npm run lint`: exit 0, warning 0
4. `npm run build:poc`: exit 0. Vite build 성공, 기존 500 kB 초과 chunk 경고는 비차단이다.
5. `npm run test:poc-server`: build 후 최종 31 pass, 0 fail. 위 정적 POC 응답도 200으로 성공했다.
6. `git diff --check`: pass

테스트 double을 양 경로 모두 빈 row 상태에서 확인하도록 마지막 조정한 뒤 state-store 단일 테스트를
재실행했고 11/11 성공했다.

## 5. 남은 범위와 판정

이 변경은 동일 PostgreSQL 인스턴스의 해당 stable advisory key를 사용하는 두 transaction만
직렬화하는 F-01 보수다. TARGET 환경 concurrency/load 검증, production gate, PREP/OPS 작업은 수행하지
않았고 push/merge도 하지 않았다. `G1-G4 NOT_APPROVED`를 유지한다.
