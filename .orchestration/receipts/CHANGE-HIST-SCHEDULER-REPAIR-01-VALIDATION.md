# 영수증: CHANGE-HIST-SCHEDULER-REPAIR-01 독립 검증

## 결과

- Task: `task_4e5aea31a283`
- 판정: `PASS`
- 대상 HEAD: `bc59cd2051d96cb306d401fb7ce37a1287275e2d`
- 비교 범위: `a937b1b1da04df8edc0bda3b0b37911e1660bc9c..bc59cd2051d96cb306d401fb7ce37a1287275e2d`
- 실제 런타임: Node `v25.9.0`, npm `11.12.1`
- source repair: 없음
- 허용 쓰기: 이 validation receipt와 대응 evidence만
- G1/G2/G3/G4: `NOT_APPROVED`

## 검토 receipt

- stored exact canonical UTC 검증: `PASS`
- newer 저장 경계에 대한 older 요청의 typed `stale`, no task/no write/no regression: `PASS`
- exact replay `already_completed`, no task/no write: `PASS`
- malformed 저장 경계의 task/write 전 fail closed: `PASS`
- PostgreSQL 이전 경계 CAS + strict timestamp compare + exact one-row `RETURNING`: `PASS`
- hardcoding/guard weakening 정적 검토와 `git diff --check`: `PASS`

## 실행 receipt

1. focused scheduler/state-store: `PASS 13/13`
2. lint: `PASS`, zero warning
3. `build:poc`: `PASS` (500 kB chunk-size warning만 존재)
4. `test:poc-server`: `PASS 28/28`

`frontend/node_modules` 부재로 `npm ci --ignore-scripts`를 exact lockfile에 대해 실행했다. 설치 전후
package SHA-256은 `f331ee0a3314b0b40da9fa309f54181be540240ef310acd8cab67d2512e28f6f`, lock SHA-256은
`3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`로 동일하며 두 파일은 변경되지
않았다.

Node 22, live PostgreSQL contention, Kafka/Schema Registry/DataHub, TARGET Linux/AMD64, 배포,
service/container, PREP/OPS, push/merge는 `NOT_EXECUTED`다. 상세 근거는
`.orchestration/evidence/CHANGE-HIST-SCHEDULER-REPAIR-01-VALIDATION.md`에 있다.
