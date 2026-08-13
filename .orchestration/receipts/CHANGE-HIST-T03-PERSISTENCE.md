# 영수증: CHANGE-HIST-T03-PERSISTENCE

## 계약

- task: `task_2f4d17d0e250`
- dispatch: `ctx_93957fc9faaa`
- exact base SHA: `d7300c3f896b817f7c98930f4a9d566497b65dc7`
- result SHA: 이 영수증을 포함하는 self-referential local commit이며 exact SHA는 `worker_done`에 기록한다.
- commit message: `feat: add change history persistence foundation`
- 범위: capture source, normalized ledger, partition checkpoint/lease-fence,
  append-only CR link history의 T03 persistence foundation만 구현한다.
- source-event fan-out: 별도 inbox 없이
  `(workspace_id, source_id, source_event_identity, deterministic_ordinal)` unique로 해결한다.

## 구현 결과

- `change_history.sources`, `ledger_events`, `checkpoints`, `cr_link_events` 네 테이블만 추가했다.
- ledger에는 closed category/aspect/precision vocabulary, bounded normalized JSON,
  nested raw-provider key 차단, source-event ordinal fan-out idempotency를 강제했다.
- checkpoint는 partition별 optimistic version, lease token hash, owner fingerprint,
  monotonic fence epoch/offset과 stale writer 거부 함수로 구성했다.
- CR link는 CR aggregate를 변경하지 않는 append-only SET/CLEAR/ADD/REMOVE event chain으로 두고,
  ledger row lock, version/prior hash 검증, replay idempotency를 강제했다.
- 네 테이블 모두 workspace composite FK, `ENABLE/FORCE ROW LEVEL SECURITY`, workspace policy,
  non-cascade FK를 적용했다. app role에는 evidence UPDATE/DELETE 권한을 부여하지 않는다.
- `0096` additive revision과 canonical `0001` baseline, revision gate, migration scope,
  generator/static verifier/data-model 문서를 동기화했다.
- T04 consumer/decode/normalization, API, UI, current-state reconciliation, CR state mutation,
  source-event inbox는 추가하지 않았다.

## 검증

- baseline generator 2회 SHA 비교: `PASS`
  - 최종 SHA-1: `a9d0e7584f8a902914cec158fb2378e6b5ad8917`
- focused unit/integration collection:
  `PASS` — `7 passed, 1 skipped`
  - skip은 정식 owner/app role 및 secret-ref가 제공된 isolated integration harness 전용이다.
- focused Ruff: `PASS`
- focused strict mypy: `PASS` — 5 source files, no issues
- `scripts/verify_static.py`: `PASS`
- `git diff --check`: `PASS`
- exact isolated database: `datariver_t03_validation_20260813`
  - 사전 부재 확인 후 생성: `PASS`
  - 최소 0095 FK prerequisite에서 0096 upgrade/downgrade/re-up: `PASS`
  - table 4, forced RLS 4, policy 4, fan-out unique 1, enabled user trigger 5: `PASS`
  - protected SECURITY DEFINER function PUBLIC EXECUTE 0: `PASS`
  - source/ledger replay, ordinal fan-out, checkpoint advance/stale fence 거부: `PASS`
  - append-only mutation 거부, CR link SET/replay/CLEAR chain: `PASS`
  - nested raw `schemaMetadata` DB constraint 거부: `PASS`
  - non-empty evidence downgrade 거부: `PASS`
  - exact database drop 후 remaining 0: `PASS` — disposable 검증 DB는 복구되지 않는다.
- credential은 출력하거나 파일에 기록하지 않고 기존 container environment에서만 참조했다.

## NOT_EXECUTED

- 전체 canonical 0001→0095 실제 history migration:
  기존 isolated PostgreSQL cluster에 `datariver_owner`/`datariver_app` 역할이 없고,
  과거 0011 revision은 offline SQL rendering 중 DB introspection을 요구하므로 실행하지 않았다.
  대신 exact task DB 안의 최소 0095 prerequisite로 0096 자체를 실제 실행했다.
- 정식 `datariver_app` 역할로 수행하는 cross-workspace RLS 및 grant integration:
  cluster-global 역할 생성은 isolated task-database 경계를 넘으므로 실행하지 않았다.
- provider/DataHub/Kafka offset·group, container lifecycle, PREP/OPS mutation
- dependency/lockfile 변경
- T04/API/UI/current-state reconciliation 및 CR aggregate state mutation
- merge, push
