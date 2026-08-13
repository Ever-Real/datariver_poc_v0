# CHANGE-HIST-SCHEDULER 구현 증적

- 기준 SHA: `4eb9ce95ec45515f5954350b27abf2874c0dd9da`
- 검증 런타임: Node `v25.9.0` (Node 22로 오표기하지 않음)
- 구현: 단일 POC 서버 내부의 KST/IANA 일일 scheduler, startup missed-run catch-up,
  PostgreSQL session advisory lock singleton, MCL capture 뒤 T05 Catalog reconciliation 순서,
  두 단계와 receipt write가 모두 성공한 경우에만 성공 boundary 기록, graceful shutdown,
  경계 검증 수동 trigger, 기본 비활성 및 MCL 설정 누락 시 기존 startup 유지.
- dependency/framework/service/container 추가: 없음
- package/lock 변경: 없음 (`npm ci --ignore-scripts`는 기존 exact lockfile 검증 설치에만 사용)

## 실행 증적

- `node --test poc-change-history-scheduler.test.mjs poc-state-store.test.mjs`: PASS, 12/12
- `npm run lint`: PASS
- `npm run build:poc`: PASS (기존 500 kB chunk 경고만 존재)
- `npm run test:poc-server`: PASS, 28/28

## 미실행

- 실제 PostgreSQL 다중 프로세스 advisory-lock 경쟁: 로컬 double로 계약 검증, 대상 배포 미실행
- 실제 Kafka/Schema Registry/DataHub 연동 일일 run: 자격증명/서비스 없는 소스 검증 환경이라 미실행
- Node 22 대상 런타임: 현재 shell이 Node v25.9.0이므로 미실행
