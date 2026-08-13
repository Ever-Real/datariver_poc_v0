# 영수증: CHANGE-HIST-T03-INDEPENDENT-VALIDATION

## 계약 및 provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_8df295acd2b2`
- dispatch: `ctx_4987ae64beb7`
- owner role: `50_QUALITY_VALIDATION`
- preferred model: Gemini 3.1 Pro via Antigravity
- actual model: `gpt-5.6-sol` controlled fallback
- reasoning: High
- exact candidate SHA: `08db16abb354543131e2c348aca47f416bdd05e2`
- validation-doc result SHA: 이 영수증을 포함하는 focused local docs commit이며 exact SHA는
  `worker_done`에 기록한다.
- 허용 쓰기: 이 영수증과
  `.orchestration/evidence/CHANGE-HIST-T03-VALIDATION.md`만 사용했다.

## 결과

- verdict: `FAIL`
- blocker: `F-01 BLOCKED_BY_LEASE_CLOCK_AUTHORITY`
- 내용: `claim_checkpoint_v1`이 DB 현재 시각 대신 호출자 제공 `p_acquired_at`으로 기존 lease
  만료를 판단하여, 실제 lease가 유효한 동안 미래 시각 claim으로 fence 탈취가 가능했다.
- 재현: 첫 claim `version 2/fence 1/offset 100` 직후 미래 시각 claim이
  `version 3/fence 2/offset 100`으로 승인되었다.
- source repair: `NOT_EXECUTED` — 명시적으로 금지됨.

## PASS

- exact candidate/clean start, 네 테이블과 PK/FK/check/unique/index
- source-event+ordinal dedup, same-field distinct event, bounded normalized JSON 및 nested raw key 거부
- timestamptz, 무 TTL/cleanup, forced RLS 4, policy 4, PUBLIC SECURITY DEFINER execute 0
- append-only trigger, offset 감소 거부, stale prior/fence 거부, CR link replay/chain/clear
- focused Ruff format/lint, strict mypy, `7 passed, 1 skipped`, static verifier
- 별도 임시 복사본 canonical `0001` regeneration SHA 일치
- non-empty downgrade 거부, empty downgrade/re-up, exact isolated DB 최종 삭제
- git diff check와 conflict marker scan

## NOT_EXECUTED

- 정식 app role cross-workspace RLS/grant live test: cluster-global 역할 미존재, 역할 생성 금지
- canonical `0001 → 0095` 전체 실제 migration history
- 전체 backend/product runtime test
- 정상 DB, provider/DataHub/Kafka, 새 container/service, PREP/OPS
- dependency/lockfile 변경, source repair, merge, push, integration/publication
- G1/G2/G3/G4는 모두 `NOT_APPROVED`

## cleanup

- exact isolated DB `datariver_t03_validation_20260813`: 최종 catalog count `0`
- credential 값: 출력/기록하지 않았고 기존 컨테이너 내부 환경에서만 사용
- 시작과 live 검증 종료 전 제품 source diff: 없음
