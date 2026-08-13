# CHANGE-HIST-T03 fresh 재검증 증거

## 판정

- 최종 판정: `PASS`
- 차단 발견: 없음
- exact candidate SHA: `5177f920b0ffe35aa9a2e09287a6cc4046a12ac5`
- 비교 base SHA: `d7300c3f896b817f7c98930f4a9d566497b65dc7`
- 원래 실패 후보 SHA: `08db16abb354543131e2c348aca47f416bdd05e2`
- F-01 수리 전 증거 commit: `1394c8522fb9572a75ac9604b3fe8e35955c8565`
- 검증 환경: DEV Mac arm64, 기존 `datariver-poc-pgvector-1` PostgreSQL 17 계열
- 격리 DB: `datariver_t03_validation_20260813`만 생성·검증·삭제했고 최종 부재 수는 `0`이다.
- source repair: `NOT_EXECUTED` — 제품·마이그레이션·테스트·설정 소스는 수정하지 않았다.
- 쓰기 범위: 이 evidence와 대응 receipt 두 신규 문서만 작성했다.
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## F-01 fresh 재현 결과

기존 실패 원인은 `claim_checkpoint_v1`이 호출자 제공 `p_acquired_at`을 lease 유효성 비교에
사용하여 실제 DB 시각보다 미래 값을 보낸 두 번째 호출자가 유효 lease를 조기 탈취할 수 있다는
것이었다. exact candidate에서는 다음을 소스와 실제 격리 PostgreSQL에서 독립 확인했다.

- SQL 함수와 repository 공개 API에서 `p_acquired_at`/`p_expires_at` 절대시각 인자가 제거되었다.
- 공개 claim 시그니처는 양의 `p_lease_duration_seconds integer`만 받는다.
- 획득 시각은 `clock_timestamp()`이고 만료 시각은 DB 시각에 duration을 더해 계산한다.
- 600초 lease의 `lease_acquired_at`은 호출 전후 DB 시각 범위 안에 있었고 만료 간격은 정확히
  600초였다.
- 실제 만료 전 다른 owner/token의 즉시 takeover는 SQLSTATE `55P03`으로 거부되었다.
- 현재 version/fence의 `100 → 101` advance는 성공했다.
- 이전 version/fence 재사용은 SQLSTATE `40001`, 직접 offset `101 → 99` 감소는 `23514`로
  거부되었다.

따라서 `F-01 BLOCKED_BY_LEASE_CLOCK_AUTHORITY`는 재현되지 않았고 `FIXED/PASS`로 판정한다.

## 계약별 결과

| 항목 | 분류 | fresh 증거 |
|---|---|---|
| exact SHA 및 clean start | `PASS` | HEAD가 exact candidate와 일치했고 시작 `git status --short`가 비어 있었다. |
| 네 테이블 최소 모델 | `PASS` | `sources`, `ledger_events`, `checkpoints`, `cr_link_events` 네 테이블만 추가된다. |
| PK/FK/check/unique/index | `PASS` | 격리 DB에서 change-history constraint `79`, index `22`; Workspace composite FK와 non-cascade 계약을 소스와 실 DB에서 재확인했다. |
| source-event + ordinal dedup | `PASS` | 동일 event exact replay는 같은 ID를 반환했고 conflicting replay는 거부됐으며 ordinal `0/1` fan-out은 허용됐다. |
| 동일 field의 서로 다른 사건 | `PASS` | 동일 normalized field key에 다른 source-event identity/offset을 가진 사건이 별도 row로 저장됐다. |
| bounded normalized data/raw key 차단 | `PASS` | unit bound 검증과 격리 DB nested `schemaMetadata` check violation(`23514`)을 확인했다. |
| UTC timestamptz | `PASS` | change-history timestamp-with-time-zone column `17`개를 확인했다. |
| 무기한 원장·link 보존 | `PASS` | TTL/expiry/pruning/partition-detach 계약이 없고 non-empty downgrade가 증거 삭제를 거부했다. lease expiry는 checkpoint 동시성 제어일 뿐 retention이 아니다. |
| forced Workspace RLS | `PASS` | 네 테이블 모두 RLS enabled/forced이고 `workspace_isolation` policy가 4개다. |
| grant/append-only 보호 | `PASS` | PUBLIC SECURITY DEFINER execute 수가 `0`; ledger UPDATE는 `23514`; ordinary evidence UPDATE/DELETE grant가 없음을 migration/static 검사로 확인했다. |
| 실제 app-role cross-workspace RLS/grant | `NOT_EXECUTED` | cluster-global `datariver_owner`/`datariver_app` 역할을 만들지 말라는 경계 때문에 새 역할을 생성하지 않았다. |
| checkpoint DB-clock 권위 | `PASS` | caller absolute timestamp 부재, DB 시각 범위, 정확한 600초 duration, live takeover `55P03`을 확인했다. |
| current fence 및 stale writer | `PASS` | current advance 성공, stale version/fence `40001`, offset 감소 `23514`였다. |
| replay/dedup/fan-out | `PASS` | source replay, event exact replay, conflicting replay, deterministic ordinal fan-out과 distinct same-field event를 다시 실행했다. |
| CR link chain/replay/append | `PASS` | SET_PRIMARY, exact replay, ADD_CANDIDATE, CLEAR_PRIMARY가 순서대로 성공했고 stale prior hash는 `40001`이었다. 기존 CR aggregate는 수정하지 않았다. |
| raw provider key 거부 | `PASS` | nested `schemaMetadata`를 DB가 거부했고 unit/static guard도 통과했다. |
| empty downgrade/re-up | `PASS` | 빈 `0096 → 0095` 후 change-history table `0`, 다시 `0096` up 후 4개였다. |
| non-empty downgrade 보호 | `PASS` | evidence 저장 뒤 downgrade는 SQLSTATE `P0001`으로 거부됐고 table 4개가 유지됐다. |
| 격리 DB cleanup | `PASS` | 세 시도의 성공/실패 cleanup 모두 exact DB만 삭제했고 최종 catalog count는 `0`이다. |

## 정적·자동 검증

- focused Ruff format: `PASS` — authored/maintained Python 11 files already formatted
- focused Ruff lint: `PASS`
- strict mypy: `PASS` — 7 source/test files, no issues
- focused pytest: `PASS` — `8 passed, 1 skipped`
  - skip은 정식 owner/app role과 secret-ref가 필요한 기존 isolated integration harness다.
- `scripts/verify_static.py`: `PASS`
- deterministic canonical `0001` regeneration: `PASS`
  - candidate SHA-256:
    `ef30f28bbb98248c46ce4b54bf08559c28d632852d3e9d3ecffe85a6a83ff3ff`
  - 별도 `/tmp` 복사본 재생성 SHA-256: 동일
- `git diff --check`: `PASS`
- base-to-candidate `git diff --check`: `PASS`
- conflict marker scan: `PASS`
- 최종 candidate SHA 재확인: `PASS`

머신 생성 canonical `backend/alembic/versions/0001_initial_schema.py`를 일반 authored source와 함께
Ruff에 넣은 탐색적 명령은 generator 고유 formatting 때문에 `NOT_APPLICABLE`로 분류한다. base에서도
같은 generated-file lint 문제가 존재하며 이 파일의 요구 gate는 별도 임시 복사본에서의 deterministic
재생성 일치다. canonical 파일을 제외한 focused Ruff는 format/lint 모두 PASS했다.

## 실행한 주요 명령

- `orca orchestration task-list --run run_fe1ea01316d1 --json`
- `git rev-parse HEAD`, `git branch --show-current`, `git status --short`
- `git diff/show`로 `d7300c3..5177f92`, F-01 repair와 T03 전체 allowlist 검토
- focused `uv run ruff format --check`, `uv run ruff check`
- focused `uv run mypy`
- focused `uv run pytest -q`
- `uv run python scripts/verify_static.py`
- `/tmp`의 exact Git archive에서 `scripts/generate_initial_migration.py` 실행 및 SHA-256 비교
- 기존 PostgreSQL container 안에서 exact DB 존재 수 확인, create/drop과 최종 부재 확인
- Alembic `0096` up, empty down/re-up, live repository/SQL negative/positive harness
- `git diff --check`, base-to-candidate diff check, conflict marker scan

credential 값은 어떤 출력이나 파일에도 기록하지 않았고 기존 container environment에서만 내부
연결에 사용했다.

## NOT_EXECUTED 및 경계

- 정식 `datariver_app` 역할을 이용한 cross-workspace RLS/grant integration:
  cluster-global 역할 생성 금지 때문에 `NOT_EXECUTED`
- canonical `0001 → 0095` 전체 실제 history migration:
  과거 revision과 cluster-global role prerequisite를 만들지 않고 최소 0095 FK prerequisite에서
  `0096` 자체를 검증했으므로 `NOT_EXECUTED`
- 전체 backend suite와 제품 runtime test: focused T03 범위 밖이므로 `NOT_EXECUTED`
- 정상 `datariver` DB, provider/DataHub, Kafka, 새 runtime/service/container, PREP/OPS mutation:
  모두 `NOT_EXECUTED`
- dependency/lockfile 변경, source repair, 기존 실패 evidence/receipt 수정, merge, push,
  integration/publication: 모두 `NOT_EXECUTED`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 결론

F-01 공격 경로는 DB-authoritative clock과 duration-only API로 닫혔다. 나머지 T03 focused 계약도
선행 PASS를 신뢰만 하지 않고 소스·정적 검사·repository replay·격리 PostgreSQL up/down/live
negative case로 다시 검증했으며 FAIL은 없다. exact candidate는 fresh 재검증 기준 `PASS`이지만
G1 통합, G2 publication, PREP/OPS와 target-environment gate는 승인하거나 실행하지 않았다.
