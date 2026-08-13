# CHANGE-HIST-T04-NODE-MCL receipt

- outcome: `IMPLEMENTED_SELF_VALIDATED_PENDING_INDEPENDENT_VALIDATION`
- exact base: `9fb7deaa88dfd03d6604ecfd5e86b3c8a8c69a83`
- product commit: `5cc3652cdc82d2a033edd95003e0f5f6525c7e0e`
- product paths:
  - `frontend/package.json`
  - `frontend/package-lock.json`
  - `frontend/poc-mcl-capture.mjs`
  - `frontend/poc-mcl-capture.test.mjs`
  - `frontend/poc-state-store.mjs`
  - `frontend/poc-state-store.test.mjs`
- evidence path: `.orchestration/evidence/CHANGE-HIST-T04-NODE-MCL.md`
- dependency delta: exact `kafkajs@2.2.4`,
  `@kafkajs/confluent-schema-registry@4.1.0`; direct native binary 없음
- lock SHA-256: `3fdccef423f6b503fa9675f0fa89bccff2b11c064a536344f35c24331407a0ca`
- tests: focused Node 10/10, POC server 28/28, focused/full ESLint PASS, POC build PASS,
  `git diff --check` PASS, credential/raw logging scan PASS
- live Kafka/Schema Registry/PostgreSQL/runtime: `NOT_EXECUTED`
- Node 22.19+/Linux AMD64 offline artifact/checksum/SBOM/license: `TARGET_RECHECK_REQUIRED`
- target MCL activation: `BLOCKED_TARGET_RECHECK`
- architecture deviation: 없음
- blocker: 로컬 제품 구현 없음; independent validation 및 target recheck 필요
- gates: G1/G2/G3/G4 `NOT_APPROVED`
- publication: merge/push/PREP/OPS `NOT_EXECUTED`
