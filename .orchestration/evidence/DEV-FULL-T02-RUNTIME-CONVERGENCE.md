# DEV-FULL-T02-RUNTIME-CONVERGENCE 증거 자료

- Task: DEV-FULL-T02-RUNTIME-CONVERGENCE
- Worktree: /Users/everreal/orca/workspaces/datariver_poc_v0/dev-full-t00-runtime
- Base SHA: 0df874df12f9653a2703a9c1c0bea212b1defe4b
- Product SHA: 7bc27171fe91fd0e886aa55e986e18d9f3749ebc
- Evidence Parent: 7bc27171fe91fd0e886aa55e986e18d9f3749ebc

## 1. 수행 내용
1. `deploy/poc/docker-compose.datahub-provider.yaml` 추가: 기존 DataHub의 external network를 환경 변수(`DATAHUB_EXTERNAL_NETWORK`) 기반으로 연결하도록 구현.
2. `001-poc-state.sql`의 멱등성 검증:
   - 기존 DEV pgvector 인스턴스에 적용 전후로 `poc_change_history_ledger_events` count(13), `poc_change_history_checkpoints` max/min offset 불변 검증.
   - `LIFECYCLE` constraint 조건 추가 반영 검증.
3. Node 22.19.0으로 `datariver-poc-web-1` 컨테이너 재생성:
   - Health 상태 `healthy`
   - Node 버전: `v22.19.0`
   - DataHub GMS, Broker:29092, Schema-Registry:8081 read-only 연결 및 데이터 수신 검증 완료.

## 2. 보안/안전성 확인
- `docker-compose.poc.yaml`, `package.json`, `package-lock.json`, `Dockerfile` 등 원본 환경 변경 없음.
- Secret 및 IP 직접 출력 없이 `POSTGRES_USER` 및 DNS 이름 기반 연결 유지.

## 3. Rollback 절차
- `web` 컨테이너 재생성 시 `-f deploy/poc/docker-compose.datahub-provider.yaml` 오버라이드 제외:
  `docker compose --env-file /Volumes/SSD_Mac/workspace/datariver_poc_v0/deploy/poc/.env -f deploy/poc/docker-compose.poc.yaml up -d --no-deps --build --force-recreate web`
