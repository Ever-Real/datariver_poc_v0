# 영수증: CHANGE-HIST-T03-REPAIR-F01

## 계약 및 provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_84fe30f4c8db`
- dispatch: `ctx_ca5b4c84f08c`
- owner role: `40_DATA_AI_KNOWLEDGE` (backend/data Builder)
- preferred model: Gemini 3.1 Pro via Antigravity
- actual model: `gpt-5.6-sol` controlled fallback
- reasoning: High
- exact base SHA: `1394c8522fb9572a75ac9604b3fe8e35955c8565`
- result SHA: 이 영수증을 포함하는 focused local commit이며 exact SHA는 `worker_done`에 기록한다.
- commit message: `fix: use database clock for checkpoint leases`
- 수정 범위: 독립 검증의 `F-01 BLOCKED_BY_LEASE_CLOCK_AUTHORITY`만 수리했다.

## F-01 처리 결과

- `claim_checkpoint_v1`의 호출자 제공 `p_acquired_at`/`p_expires_at` 절대 시각을 제거했다.
- 공개 SQL 및 repository API는 양의 `lease_duration_seconds`만 받는다.
- PostgreSQL `clock_timestamp()`이 lease 획득 시각, 만료 시각, 기존 lease 유효성 및
  checkpoint advance 시점의 만료 판정을 결정한다.
- 기존 optimistic version, monotonic fence/offset, 현재 token/owner 검증과 stale writer 거부는
  유지했다.
- unit/static guard와 PostgreSQL integration test에 공개 시그니처, DB-clock interval,
  유효 lease takeover 거부 회귀를 추가했다.
- deterministic canonical `0001`과 downgrade 함수 시그니처를 동기화했다.
- T04 consumer/API/UI/reconciliation 또는 기존 CR state 계약은 변경하지 않았다.

## 검증

- exact base 및 clean start: `PASS`
- allowlist: `PASS` — 아래 9개 경로만 수정했다.
  - `backend/alembic/versions/0096_change_history_persistence.py`
  - `backend/alembic/versions/0001_initial_schema.py`
  - `backend/src/datariver/infrastructure/db/change_history.py`
  - `scripts/generate_initial_migration.py`
  - `scripts/verify_static.py`
  - `backend/tests/unit/test_change_history_persistence.py`
  - `backend/tests/integration/test_change_history_persistence_postgres.py`
  - `docs/06_DATA_MODEL.md`
  - `.orchestration/receipts/CHANGE-HIST-T03-REPAIR-F01.md`
- focused Ruff format/lint: `PASS`
- focused strict mypy: `PASS` — 3 source/test files, no issues
- focused pytest: `PASS` — `8 passed, 1 skipped`
  - skip은 별도 환경변수와 정식 owner/app role이 필요한 integration harness다.
- `scripts/verify_static.py`: `PASS`
- deterministic canonical `0001` regeneration: `PASS`
  - 연속 생성 전후 SHA-256:
    `ef30f28bbb98248c46ce4b54bf08559c28d632852d3e9d3ecffe85a6a83ff3ff`
- `git diff --check`: `PASS`
- conflict marker scan: `PASS`
- exact isolated DB `datariver_t03_validation_20260813`: `PASS`
  - 시작 부재 확인 후 해당 DB만 생성했다.
  - 최소 `0095` prerequisite에서 `0096` up, empty down, re-up을 실행했다.
  - table 4, forced RLS 4, workspace policy 4, PUBLIC SECURITY DEFINER execute 0을 확인했다.
  - 예전 timestamp 공개 시그니처 부재와 새 duration 시그니처를 확인했다.
  - DB 획득 시각 범위와 정확한 600초 만료 interval을 확인했다.
  - 실제 만료 전 다른 owner/token takeover는 SQLSTATE `55P03`으로 거부되었다.
  - 현재 fence의 `100 → 101` advance는 성공했고 이전 version/fence는 SQLSTATE `40001`로
    거부되었다.
  - 첫 harness의 privilege count는 SECURITY INVOKER 함수까지 포함해 중단되었고, exact DB를
    즉시 삭제·부재 확인한 뒤 깨끗하게 재생성하여 SECURITY DEFINER 기준으로 최종 검증했다.
  - 성공/실패 cleanup 모두 exact DB만 삭제했으며 최종 catalog count는 `0`이다.
- credential 값은 출력하거나 파일에 기록하지 않고 기존 container environment에서만 참조했다.

## NOT_EXECUTED 및 gate

- 전체 backend suite와 제품 runtime test: focused F-01 범위 밖이라 `NOT_EXECUTED`
- 정식 `datariver_app` 역할 기반 cross-workspace integration: cluster-global role 생성 금지로
  `NOT_EXECUTED`
- canonical `0001 → 0095` 전체 실제 history migration: 기존 최소 `0095` prerequisite를 사용해
  `0096` 자체만 검증했으므로 `NOT_EXECUTED`
- 정상 `datariver` DB, provider/DataHub, Kafka, 새 service/container, PREP/OPS mutation:
  모두 `NOT_EXECUTED`
- dependency/lockfile 변경, failed validation evidence/receipt 수정, merge, push,
  integration/publication: 모두 `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 판정

- F-01: `FIXED`
- blocker: 없음
- candidate status: focused local commit 후 독립 재검증 가능
