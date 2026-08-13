# 영수증: CHANGE-HIST-T02-R1

## 기준선과 범위

- Task: `CHANGE-HIST-T02-R1`
- Exact base SHA: `8cd0d7e8f2fcfcd061eeb096e14f15d983e73874`
- Owner role: `10_ARCHITECTURE`
- Risk: `R2`, documentation-only architecture decision
- Allowed paths:
  - `docs/adr/0123-datahub-change-history-ledger.md`
  - `.orchestration/receipts/CHANGE-HIST-T02-R1.md`

## 결정 결과

- ADR-0122가 unintegrated ARCH-SEC-001 후보에 예약되어 있다는 충돌 공지를 보존하고 ADR-0123을
  사용했다.
- Timeline retained-history initial backfill과 조건부 MCL forward capture를 분리했다.
- precision을 `EXACT_TIMELINE`, `EXACT_MCL`, `DRIFT_DETECTED`, `BACKFILLED_BEST_EFFORT`,
  `INITIAL_BASELINE`의 닫힌 enum으로 정하고, 초기 backfill은 `BACKFILLED_BEST_EFFORT`, 타겟 gate
  이후 first checkpoint의 연속 MCL 범위만 `EXACT_MCL`로 한정했다.
- source-event identity, partition/offset checkpoint, deterministic dedup, DB transaction과 Kafka
  commit-loss replay를 결정했다.
- append-only normalized ledger와 atomic-generation current projection, deletion tombstone,
  raw schema/aspect document 비보존을 결정했다.
- 기존 web/PostgreSQL/pgvector/optional Redis topology와 singleton fence를 재사용하고 새
  container/service/process를 추가하지 않았다.
- deployment-configured `00:00 Asia/Seoul` nightly current-only reconciliation, UTC storage와 KST
  weekly count contract를 결정했다.
- 담당자 기본 순서를 active Data Steward, active Developer, authorized mapped DataHub Owner,
  `UNASSIGNED`로 정하고, 후보 priority는 숫자 방향을 고정하지 않는 existing policy-defined
  ordering을 따르도록 했다. append-only candidate/primary CR link history와 CR
  zero-auto-transition을 결정했다.
- weekly count를 distinct normalized change transaction 단위로 정의하고 exact
  total/unlinked/mutually-exclusive stage 식과 rejected/cancelled/candidate/non-primary 미진행 규칙을
  결정했다.
- native `Change History` Monitoring tab을 삭제/URL 변경 불가한 첫 번째 default-active tab으로
  정의하고 외부 Dashboard Link 8개 제한에서 제외했으며 필수 summary fields를 명시했다. 기존 외부
  Monitoring tab과 CR state/revision/approval/target binding은 보존했다.
- 논리 모델/API summary에 source/detect/capture 시각, effective week, history/guarantee 경계,
  Timeline/MCL 첫 checkpoint와 last successful capture watermark를 구분했다.
- Monitoring 요구 표시명과 admin/data_steward/developer/viewer의 조회·link/action·System 범위를
  기존 configurable capability catalog/System assignment에 연결하고 POC open-policy 및 기존
  authorization boundary를 보존했다.
- T03 persistence candidate는 진행 가능하지만 T04는 `BLOCKED_TARGET_RECHECK`, G1-G4는
  `NOT_APPROVED`로 유지했다.

## 검증

- new-file whitespace check: `PASS` — 두 파일의 `git diff --no-index --check` 진단이 비어 있음
  (exit 1은 새 파일 diff 존재를 나타냄).
- ADR required-section/conflict scan: `PASS` — 필수 section과 ADR-0122 예약/ADR-0123 사용을 확인함.
- allowed-path diff scan: `PASS` — working tree 변경은 허용된 두 파일뿐임.
- focused local commit: `PASS` — 허용된 두 파일만
  `docs: decide DataHub change history capture architecture`로 local commit함.

## 증거 한계

- TARGET Timeline과 category 관찰은 `TARGET_USER_OBSERVED`이며 controller 재실행 증거로 바꾸지
  않았다.
- DEV retention/MCL infrastructure 관찰은 `DEV_OBSERVED`이며 TARGET PASS로 바꾸지 않았다.
- DEV/TARGET effective retention max/time policy와 타겟 MCL decode/catch-up은
  `UNKNOWN`/`TARGET_RECHECK_REQUIRED`다.
- DataHub `v1.6.0rc1` 링크는 `SOURCE_CONFIRMED` 발견 근거이며 ADR-0008 production stable contract를
  대체하지 않는다.

## NOT_EXECUTED

- product code/migration/dependency/deployment/runtime/provider/data/container mutation
- product tests, Ruff, mypy, pytest, static verification, frontend build, browser/E2E/load/restore
- actual MCL payload decode, TARGET/PREP/OPS, merge, push, G1-G4 approval
