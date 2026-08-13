# CHANGE-HIST-SCHEDULER 구현 영수증

- 기준 SHA: `4eb9ce95ec45515f5954350b27abf2874c0dd9da`
- 제품 커밋: `660d551059e007850ad41ab2773753fe468cf58c`
- 변경 경로:
  - `frontend/poc-change-history-scheduler.mjs`
  - `frontend/poc-change-history-scheduler.test.mjs`
  - `frontend/poc-server.mjs`
  - `frontend/poc-state-store.mjs`
  - `frontend/poc-state-store.test.mjs`
  - `deploy/poc/.env.example`

## 구현 결과

- 단일 POC 서버 내부에서 IANA time zone 기준 일일 scheduler를 실행한다.
- startup missed-run catch-up을 비차단으로 수행하고 이미 성공한 boundary는 재실행하지 않는다.
- PostgreSQL session advisory lock으로 다중 프로세스 실행을 단일화한다.
- bounded MCL capture 뒤 기존 T05 Catalog reconciliation을 순서대로 실행한다.
- 두 작업과 receipt write가 모두 성공한 경우에만 성공 boundary를 기록한다.
- scheduler 비활성 또는 MCL 설정 누락 시 기존 서버 startup 동작을 유지한다.
- graceful shutdown과 정확한 day-boundary만 허용하는 수동 trigger를 제공한다.
