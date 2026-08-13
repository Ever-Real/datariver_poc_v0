# CHANGE-HIST-SCHEDULER 검증 증적

- 기준 SHA: `4eb9ce95ec45515f5954350b27abf2874c0dd9da`
- 제품 커밋: `660d551059e007850ad41ab2773753fe468cf58c`
- 검증 런타임: Node `v25.9.0` (Node 22로 오표기하지 않음)
- dependency/framework/service/container 추가: 없음
- package/lock 변경: 없음 (`npm ci --ignore-scripts`는 기존 exact lockfile 검증 설치에만 사용)

## 실행 결과

- `node --test poc-change-history-scheduler.test.mjs poc-state-store.test.mjs`: PASS, 12/12
- `npm run lint`: PASS
- `npm run build:poc`: PASS (기존 500 kB chunk 경고만 존재)
- `npm run test:poc-server`: PASS, 28/28

## 미실행

- 실제 PostgreSQL 다중 프로세스 advisory-lock 경쟁: 로컬 double로 계약 검증, 대상 배포 미실행
- 실제 Kafka/Schema Registry/DataHub 연동 일일 run: 자격증명/서비스 없는 소스 검증 환경이라 미실행
- Node 22 대상 런타임: 현재 shell이 Node v25.9.0이므로 미실행
