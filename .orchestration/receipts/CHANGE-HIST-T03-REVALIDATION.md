# 영수증: CHANGE-HIST-T03-FRESH-REVALIDATION

## 계약 및 provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_f4436fcad2a9`
- dispatch: `ctx_f9fb96e6e4e4`
- owner role: `50_QUALITY_VALIDATION`
- preferred model: Gemini 3.1 Pro via Antigravity
- actual model: `gpt-5.6-sol` controlled fallback
- reasoning: High
- exact candidate SHA: `5177f920b0ffe35aa9a2e09287a6cc4046a12ac5`
- 비교 base SHA: `d7300c3f896b817f7c98930f4a9d566497b65dc7`
- validation-doc result SHA: 이 영수증과 evidence만 포함하는 focused local docs commit이며 exact SHA는
  `worker_done`에 기록한다.
- 허용 쓰기: 이 receipt와
  `.orchestration/evidence/CHANGE-HIST-T03-REVALIDATION.md` 두 신규 문서뿐이다.
- source repair: `NOT_EXECUTED`
- permission contract: `LOW_RISK_COMMANDS_PREAPPROVED=TRUE`; exact isolated DB lifecycle 승인 범위만
  사용했다.

## 최종 판정

- verdict: `PASS`
- F-01: `FIXED/PASS`
- 신규 FAIL/blocker: 없음
- candidate SHA와 validation-doc SHA를 분리해 보고한다.
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

## 검증 요약

- exact SHA/clean start 및 최종 candidate 재확인: `PASS`
- T03 네 테이블과 PK/FK/check/unique/index: `PASS`
  - table 4, constraint 79, index 22, UTC timestamptz 17
- forced RLS/policy: `PASS` — 각 4
- PUBLIC SECURITY DEFINER execute: `PASS` — 0
- F-01 live attack: `PASS`
  - DB-clock 600초 lease
  - 다른 owner/token takeover `55P03`
  - current fence `100 → 101` 성공
  - stale fence `40001`, offset 감소 `23514`
- replay/dedup/fan-out/distinct same-field/raw-key rejection: `PASS`
- CR SET/replay/CANDIDATE/CLEAR chain, stale prior hash, append-only: `PASS`
- empty `0096 → 0095 → 0096`: `PASS`
- non-empty downgrade 보호: `PASS` — `P0001`
- focused Ruff format/lint: `PASS`
- strict mypy: `PASS`
- focused pytest: `PASS` — `8 passed, 1 skipped`
- static verifier: `PASS`
- deterministic `0001` regeneration: `PASS`
  - SHA-256 `ef30f28bbb98248c46ce4b54bf08559c28d632852d3e9d3ecffe85a6a83ff3ff`
- diff check/conflict scan: `PASS`
- exact isolated DB cleanup: `PASS` — 최종 부재 수 `0`

세부 분류와 실행 증거는
`.orchestration/evidence/CHANGE-HIST-T03-REVALIDATION.md`에 기록했다. 머신 생성 canonical
`0001`을 일반 Ruff source로 취급한 탐색적 overbroad 실행은 `NOT_APPLICABLE`; canonical 요구 gate인
별도 임시 복사본 deterministic regeneration과 maintained source focused Ruff는 모두 PASS다.

## NOT_EXECUTED

- cluster-global role 생성 및 정식 `datariver_app` cross-workspace integration
- canonical `0001 → 0095` 전체 실제 history migration
- 전체 backend suite와 제품 runtime
- 정상 `datariver` DB, provider/DataHub, Kafka, 새 runtime/service/container, PREP/OPS
- dependency/lockfile 변경, source/migration/test/config repair
- 기존 실패 evidence/receipt 수정, merge, push, integration/publication
- G1/G2/G3/G4 승인

credential 값은 출력하거나 문서에 기록하지 않았다. 실패한 두 사전 harness 시도도 exact DB만
정리했고 각각 최종 부재 수 `0`을 확인한 뒤 수정된 harness로 최종 PASS를 얻었다.
