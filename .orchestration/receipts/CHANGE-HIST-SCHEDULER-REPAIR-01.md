# 영수증: CHANGE-HIST-SCHEDULER-REPAIR-01

## 결과

- 판정: `PASS_LOCAL`
- exact base: `a937b1b1da04df8edc0bda3b0b37911e1660bc9c`
- product commit: `2b6d8bf7d5b4190e648be5ee38b781ac9e335241`
- runtime: Node `v25.9.0`, npm `11.12.1`
- 변경 범위: `frontend/poc-state-store.mjs`, `frontend/poc-state-store.test.mjs`
- package/lock/dependency/service/container/config/UI/CR/Python 변경: 없음
- G1/G2/G3/G4: `NOT_APPROVED`

## F-01 repair receipt

기존 session advisory lock 안에서 저장 `last_successful_schedule`을 exact explicit UTC timestamp로
검증한다. equality는 `already_completed`, 저장 경계가 요청보다 최신이면 secret 없는 typed `stale`
no-op으로 종료하며 두 경우 모두 ordered task와 receipt write를 호출하지 않는다.

receipt upsert에는 읽은 이전 경계 CAS와 strict timestamp 비교 조건을 추가했고 `RETURNING` 한 행이 요청
경계와 정확히 일치해야만 `succeeded`를 반환한다. newer 성공→older manual→exact replay 회귀에서 task는
1회, older는 `stale`, replay는 `already_completed`, 최종 receipt는 newer로 유지됐다. malformed 저장
경계와 conditional zero-row는 fail closed한다.

## 검증 receipt

- focused scheduler/state-store: `PASS 13/13`
- lint: `PASS`
- POC build: `PASS` (기존 chunk-size warning만 존재)
- POC server: `PASS 28/28`
- `git diff --check`: `PASS`
- 검증용 `npm ci --ignore-scripts`: 기존 exact lockfile 설치만 수행, package/lock unchanged

상세 증적은 `.orchestration/evidence/CHANGE-HIST-SCHEDULER-REPAIR-01.md`에 있다. Node 22/TARGET, live
PostgreSQL contention, Kafka/Schema Registry/DataHub, 배포/PREP/OPS, push/merge는 `NOT_EXECUTED`다.
