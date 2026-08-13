# CHANGE-HIST-T03 독립 검증 증거

## 판정

- 최종 판정: `FAIL`
- 차단 상태: `BLOCKED_BY_LEASE_CLOCK_AUTHORITY`
- exact candidate SHA: `08db16abb354543131e2c348aca47f416bdd05e2`
- 비교 base SHA: `d7300c3f896b817f7c98930f4a9d566497b65dc7`
- 검증 환경: DEV Mac arm64의 기존 `datariver-poc-pgvector-1` PostgreSQL 17 계열
- 격리 DB: `datariver_t03_validation_20260813`만 생성·검증·삭제했으며 최종 부재 수 `0`
- source repair: `NOT_EXECUTED` — 독립 검증 계약에 따라 제품/마이그레이션/테스트 소스를 수정하지 않았다.

## 차단 발견

### F-01 — 유효 lease를 미래 호출자 시각으로 즉시 탈취 가능

분류: `FAIL`

`change_history.claim_checkpoint_v1`은 기존 lease가 유효한지 DB 현재 시각이 아니라 호출자가
제공한 `p_acquired_at`과 비교한다. 첫 claim을 실제 현재 시각부터 10분 동안 설정한 직후, 두 번째
호출에서 `p_acquired_at`을 11분 미래로 전달하자 실제 lease 만료 전인데도 claim이 승인되었다.

재현 결과는 다음과 같다.

- 첫 claim: `checkpoint_version=2`, `fence_epoch=1`, `next_offset=100`
- 실제 만료 전 미래 시각 claim: `checkpoint_version=3`, `fence_epoch=2`, `next_offset=100`
- 이전 owner의 `version=2/fence=1` advance: `serialization_failure`로 거부
- 새 fence의 정상 advance: `checkpoint_version=4`, `fence_epoch=2`, `next_offset=101`

즉 fence가 stale writer를 사후 거부하는 부분은 동작하지만, 아직 유효한 owner를 DB 시각 전에
축출할 수 있다. 이는 durable lease/fence의 현재 owner 보장과 stale-writer 계약을 충족하지 못한다.
호출자 시각을 DB 권위 시각에 고정하거나 허용 가능한 clock 계약을 DB에서 검증하는 source
수정과 새 negative test가 필요하다. 이 Task는 source repair가 금지되어 있어 수정하지 않았다.

## 계약별 검증 결과

| 항목 | 분류 | 독립 증거 |
|---|---|---|
| exact SHA 및 clean start | `PASS` | HEAD가 exact candidate와 일치했고 시작 `git status --short`가 비어 있었다. |
| 네 테이블 최소 모델 | `PASS` | `sources`, `ledger_events`, `checkpoints`, `cr_link_events` 네 테이블만 추가되었다. |
| PK/FK/check/unique/index | `PASS` | 격리 DB에서 change-history constraint `79`, index `22`; Workspace composite FK와 non-cascade 계약을 소스/실 DB에서 확인했다. |
| source-event + ordinal dedup | `PASS` | 동일 source-event/ordinal 중복은 unique violation, ordinal `0/1` fan-out은 허용되었다. |
| 동일 field의 서로 다른 사건 | `PASS` | 같은 normalized field key에 서로 다른 source event를 포함한 총 3개 ledger row가 허용되었다. |
| bounded normalized data/raw key 차단 | `PASS` | unit bound 검증과 격리 DB의 nested `schemaMetadata` check violation을 확인했다. |
| UTC timestamptz | `PASS` | change-history의 timestamp-with-time-zone column `17`개를 확인했다. |
| 무기한 보존 | `PASS` | 네 테이블과 migration에 TTL/expiry/cleanup deletion 경로가 없고, evidence가 있는 downgrade는 거부되었다. |
| forced Workspace RLS | `PASS` | 네 테이블 모두 RLS enabled/forced, `workspace_isolation` policy 4개였다. |
| app grant/append-only 소스 계약 | `PASS` | app role에는 evidence UPDATE/DELETE가 없고 checkpoint는 SECURITY DEFINER 함수로만 변경된다. PUBLIC SECURITY DEFINER execute 수는 `0`이었다. |
| 실제 app-role cross-workspace RLS/grant | `NOT_EXECUTED` | cluster-global `datariver_owner`/`datariver_app` 역할이 없었고 계약에 따라 역할을 생성하지 않았다. |
| ledger/CR link append-only | `PASS` | CR link UPDATE와 ledger/source evidence mutation guard를 확인했고 enabled user trigger는 5개였다. |
| checkpoint offset monotonicity | `PASS` | `101 → 99` 직접 감소가 check violation으로 거부되었다. |
| lease/fence 현재 owner 보장 | `FAIL` | F-01의 미래 `p_acquired_at` 즉시 탈취가 재현되었다. |
| stale writer advance 거부 | `PASS` | 탈취 후 이전 version/fence advance가 거부되었다. |
| CR link chain/replay/append | `PASS` | SET_PRIMARY, exact replay no-op, ADD_CANDIDATE, CLEAR_PRIMARY와 stale prior hash 거부를 확인했다. 최종 primary는 null이었다. |
| 기존 CR state machine 무변경 | `PASS` | candidate diff에 기존 CR state/transition/approval/target-binding 소스 변경이 없다. |
| non-empty downgrade 보호 | `PASS` | evidence가 있는 `0096 → 0095`는 명시적으로 거부되었고 revision/table은 `0096`/4로 유지되었다. |
| empty downgrade/re-up | `PASS` | 빈 `0096 → 0095`에서 revision `0095`, change-history table `0`; re-up 후 `0096`, table `4`였다. |
| 격리 DB cleanup | `PASS` | exact DB drop 후 PostgreSQL catalog의 동일 이름 수가 `0`이었다. |

## 실행한 자동 검증

- focused Ruff format: `PASS` — 10 files already formatted
- focused Ruff lint: `PASS`
- strict mypy: `PASS` — 7 source files, no issues
- focused unit/integration pytest: `PASS` — `7 passed, 1 skipped`
- `scripts/verify_static.py`: `PASS`
- deterministic canonical `0001` regeneration: `PASS`
  - candidate SHA-1: `a9d0e7584f8a902914cec158fb2378e6b5ad8917`
  - 별도 임시 복사본 재생성 SHA-1: 동일
- `git diff --check`: `PASS`
- base-to-candidate `git diff --check`: `PASS`
- conflict marker scan: `PASS`

## NOT_EXECUTED 및 경계

- 정식 `datariver_app` 역할을 이용한 cross-workspace RLS 및 grant integration:
  cluster-global 역할 생성 금지 때문에 `NOT_EXECUTED`
- canonical `0001 → 0095` 전체 실제 history migration:
  격리 cluster에 정식 owner/app 역할이 없고 과거 revision의 DB introspection 계약이 있어
  `NOT_EXECUTED`; 최소 0095 FK prerequisite에서 0096 자체를 실제 실행했다.
- 전체 backend suite와 제품 runtime test: focused T03 범위 외이므로 `NOT_EXECUTED`
- 정상 `datariver` DB, provider/DataHub, Kafka, 새 runtime/service/container, PREP/OPS mutation:
  모두 `NOT_EXECUTED`
- dependency/lockfile 변경, merge, push, integration/publication: 모두 `NOT_EXECUTED`
- G1/G2/G3/G4: `NOT_APPROVED`

## 결론

DDL, RLS, append-only, dedup, replay, migration cycle의 나머지 focused 계약은 통과했다. 그러나
F-01은 lease의 실제 현재 owner를 조기 축출할 수 있어 `FAIL`이며 candidate 완료를 차단한다.
source repair와 재검증 없이는 G1 후보로 승인할 수 없다.
