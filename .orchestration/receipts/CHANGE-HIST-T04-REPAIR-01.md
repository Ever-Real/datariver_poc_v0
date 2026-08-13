# CHANGE-HIST-T04-REPAIR-01 receipt

## provenance

- Orca run: `run_fe1ea01316d1`
- task: `task_8a25b69c4c79`
- dispatch: `ctx_d521e2a12acb`
- owner role: `40_DATA_AI_KNOWLEDGE`
- actual model: `gpt-5.6-sol` controlled fallback, reasoning High
- exact base: `d3df8b29d83a0c324dc9b806e8d9506b141c162a`
- product commit: `79497a5900fed05b80f681af7f14fcb0fddf0845`
- evidence commit: 이 receipt와 evidence를 포함하는 별도 focused local commit

## 결과

- outcome: `REPAIRED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`
- F-01: 최초 전체 partition `B[p]`를 source-row 직렬화와 단일 PostgreSQL transaction으로 consumer
  생성 전에 영속화; empty/non-empty, retention gap, new/missing topology, boundary rollback,
  concurrent/duplicate initialization focused contract `PASS`
- F-02: supported GenericAspect의 모든 non-null wrapper에 정확한 `application/json` 적용;
  valid/missing/`application/avro`/non-JSON negative contract `PASS`
- product paths:
  - `frontend/poc-mcl-capture.mjs`
  - `frontend/poc-mcl-capture.test.mjs`
  - `frontend/poc-state-store.mjs`
  - `frontend/poc-state-store.test.mjs`
- evidence paths:
  - `.orchestration/evidence/CHANGE-HIST-T04-REPAIR-01.md`
  - `.orchestration/receipts/CHANGE-HIST-T04-REPAIR-01.md`
- dependency/package/lock delta: 없음
- focused Node: `13/13 PASS`
- full frontend ESLint: `PASS`
- POC build: `PASS`, 기존 chunk-size warning만 존재
- POC server regression: `28/28 PASS`
- diff/allowlist/secret/conflict scan: `PASS`
- 임시 `frontend/node_modules` symlink: 제거 완료
- live Kafka/Schema Registry/PostgreSQL/runtime/provider/container: `NOT_EXECUTED`
- Node 22.19+ exact/Linux AMD64: `TARGET_RECHECK_REQUIRED`
- architecture deviation: 없음
- blocker: 로컬 repair 없음; fresh independent validation 필요
- gates: G1/G2/G3/G4 `NOT_APPROVED`
- publication: merge/push/PREP/OPS `NOT_EXECUTED`
