# PROJECT_HANDOFF_RECONCILIATION.md

## BASELINE
- repository: /Volumes/SSD_Mac/workspace/datariver_poc_v0
- exact_sha: af97af3c5c77449398711fbf33638aad1f980499
- branch: dev; origin/dev same SHA; origin/main ABSENT
- dirty_state: only harness paths (.orchestration, CURRENT.md, PRODUCT_CONTROL.md)
- environment: DEV_MAC_ARM64

## WORKSTREAM_STATUS
| Workstream | Status | Evidence | Main Gap |
|---|---|---|---|
| Runtime/Release | PARTIAL | frontend/package.json, deploy/poc Dockerfile and Compose define web+PostgreSQL/pgvector+Redis+Neo4j and env contracts | current execution absent; POC Compose has no pull_policy never; image provenance accepts local/unrecorded and stale source-base; PREP/OPS unknown |
| Catalog/Search | IMPLEMENTED_UNVERIFIED | Static server/UI/tests cover cursor inventory, matching fields, dashboard/tree/detail/profile/lineage | No current tests, browser, DataHub probe, or cardinality evidence |
| Registration/CR | PARTIAL | Manual DataHub write/readback, bulk preparation/MinIO/Airflow wiring, CR transitions and server hydration/persistCore exist | omitted manual fields may clear aspects; success enums and TEST evidence fail open/fabricate hashes; E2E not run |
| Chat/AI/Knowledge | PARTIAL | AUTO/GENERAL/VECTOR/GRAPH, bounded memory, pgvector and fixed Neo4j query paths exist | Knowledge preflight/release fabricates PASS/ACTIVE and fixed hashes; providers unexecuted |
| Quality/Governance/Admin | PARTIAL | CRUD/state and governance sanitization/permission catalog exist | Quality/Governance provider-success states and review defaults are not trustworthy; one open POC identity is not maker-checker proof |
| External Integration | IMPLEMENTED_UNVERIFIED | DataHub/Airflow/MinIO/LLM/Grafana env/server contracts exist | Airflow conf is not per-DAG closed schema; HTTP credential transport can be configured; no live probes |
| UI/Legacy Parity | IMPLEMENTED_UNVERIFIED | Current shell exposes required broad routes/profile menus and compact poc badge with no large banner in static code/tests | Browser validation and full datariver_v0 parity matrix NOT_EXECUTED |
| E2E/Release | MISSING | Existing test code is not execution evidence | current-SHA evidence |

## VERIFIED_DONE
- Repository/SHA/branch/origin-dev baseline.
- Minimal control-plane harness and command permission policy exist.
- Nine role sessions have been initialized; only 00 and 98 persistent active.
- Static audit confirmed fixed server-owned DataHub GraphQL and Neo4j Cypher; no browser raw GraphQL/Cypher pass-through in audited paths.
- Static audit confirmed provider redirects rejected, browser runtime config does not expose credentials, and governance sanitizer blocks active/embedded elements in audited file.

## IMPLEMENTED_UNVERIFIED
- Catalog/Search
- External Integration
- UI/Legacy Parity

## PARTIAL
- Runtime/Release
- Registration/CR
- Chat/AI/Knowledge
- Quality/Governance/Admin

## MISSING
- E2E/Release

## PRE_EXISTING_ISSUES
C1 unauthenticated LAN-bound server-held provider authority; reconcile with user's required 0.0.0.0 through an explicit ingress/ACL design, not by silently removing LAN bind.
H1 unvalidated whole-state persistence/hydration bypass.
H2 fail-open decisions and fabricated TEST evidence hashes.
H3 allowlisted Airflow DAG with arbitrary conf/reserved-key override.
H4 omitted manual metadata fields can destructively clear live DataHub aspects.
H5 Knowledge preflight/publication fabricated PASS/ACTIVE and hashes.
M1 Quality/Governance fabricated provider-success states.
M2 DataHub cache authorization/freshness binding gap.
M3 PostgreSQL target identity guard gap.
M4 plaintext credential-bearing provider URLs allowed.
M5 support services host-published to loopback and linux/amd64 default requires portability reconciliation.
M6 stale/placeholder container image provenance.
M7 provider metadata prompt-injection boundary gap.
L1 last-writer-wins core snapshot.
L2 evidence-shaped fixed constants.

## BLOCKERS
- runtime permission prompts
- worktree policy conflict
- PREP/OPS external evidence

## ENVIRONMENT_GAPS
- DEV: DEV_MAC_ARM64
- PREP: PREP_WSL_AMD64 UNKNOWN
- OPS: OPS_LINUX_AMD64 UNKNOWN

## PROPOSED_TASK_DAG
All planned base SHA values are the current SHA but MUST be rebound to the then-current exact SHA before dispatch.

1 ARCH-SEC-001 owner 10 R3 depends CP-RECON-DOC-001 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed docs/adr/0122-poc-mutation-evidence-boundary.md acceptance: reconcile 0.0.0.0 with ingress/ACL, state command/schema boundary, fail-closed enums, evidence semantics, provider write semantics; required_validation 90; gate NONE for planning.
2 SEC-INGRESS-001 owner 30 R3 depends ARCH-SEC-001 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/poc-server.mjs, frontend/poc-server.test.mjs, deploy/poc/docker-compose.poc.yaml, deploy/poc/.env.example, deploy/poc/POC_LIMITATIONS.md acceptance: explicit safe LAN exposure contract and negative unauthorized mutation tests; required_validation 50+90; gate G1 before integration.
3 STATE-BOUNDARY-001 owner 40 R3 depends ARCH-SEC-001 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/poc-server.mjs, frontend/poc-state-store.mjs, frontend/src/poc/pocApi.ts, focused tests, deploy/poc/postgres-init/001-poc-state.sql acceptance: strict state schemas/transition validation/CAS and DB identity guard; required_validation 50+90; gate G1.
4 EVIDENCE-INTEGRITY-001 owner 40 R3 depends ARCH-SEC-001 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/src/poc/pocContracts.ts, frontend/src/poc/pocApi.ts, focused tests acceptance: remove fabricated hashes/timestamps/success defaults; compute canonical evidence or explicit null NOT_EVIDENCE; required_validation 50+90; gate G1.
5 PROVIDER-WRITE-001 owner 40 R3 depends ARCH-SEC-001 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/poc-server.mjs, frontend/poc-server.providers.test.mjs acceptance: closed Airflow conf, immutable trusted marker, patch-vs-clear DataHub semantics, conflict/readback; required_validation 50+90; gate separate user gate.
6 VAL-FOUNDATION-001 owner 50 R2 depends 2,3,4,5 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed read-only repository and existing validation outputs acceptance: typecheck/lint/test:poc/test:poc-server/build:poc/compose-config evidence at exact SHA; no repair; required_validation 00 evidence review; gate NONE.
7 PLATFORM-RUNTIME-001 owner 20 R2 depends 6 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed deploy/poc/**, frontend/package.json, relevant release docs acceptance: native/Compose DEV contract, offline no-pull procedure, exact SHA image labels/checksum, ARM64/AMD64 split; required_validation 50; gate runtime/container mutation separately governed.
8 CATALOG-001 owner 40 R2 depends 6 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/poc-server.mjs, frontend/src/poc/**, focused tests acceptance: live full inventory/search/tree/detail/profile/lineage with zero-vs-failure evidence; required_validation 50+60; gate separate user gate.
9 WORKFLOW-001 owner 40 R3 depends 5,6,8 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/poc-server.mjs, frontend/src/poc/**, focused tests acceptance: Manual/BULK/MinIO/Airflow/DataHub readback and full CR transition/revision/attachment E2E; required_validation 50+60+90; gate external mutations gated.
10 AI-KNOWLEDGE-001 owner 40 R2 depends 4,6,8 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/poc-server.mjs, frontend/poc-state-store.mjs, frontend/src/poc/**, focused tests acceptance: evidence-grounded Chat/vector/graph/session memory and non-fabricated Knowledge/Glossary; required_validation 50+60+90; gate separate user gate.
11 QGA-001 owner 30 with 40 support R3 depends 3,4,6 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/src/poc/**, governance sanitizer path, focused tests acceptance: real/explicitly unavailable Quality, safe Governance CRUD, Admin/permission/retention semantics; required_validation 50+60+90; gate separate user gate.
12 UI-PARITY-001 owner 60 R1 depends 8,9,10,11 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed frontend/src/poc/** and exact read-only datariver_v0 references acceptance: page/menu/button/API/persistence/error/empty/provider failure parity matrix and browser flows; required_validation 50; gate separate user gate.
13 E2E-001 owner 50 R3 depends 7-12 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed test/evidence outputs only acceptance: representative Catalog/Registration/CR/Chat/Knowledge/Quality/Admin results individually PASS/FAIL/PRE_EXISTING/NOT_EXECUTED; required_validation 90; gate G1/G2 remain separate.
14 PREP-001 owner 20 R3 depends 13 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed NOT_ASSIGNED_UNTIL_G3 acceptance: exact origin/dev source/artifact/checksum and WSL AMD64 evidence; required_validation none; gate G3.
15 OPS-001 owner 20 R3 depends 14 exact_base_sha af97af3c5c77449398711fbf33638aad1f980499 allowed NOT_ASSIGNED_UNTIL_G4 acceptance: PREP-verified AMD64 release and Linux evidence; required_validation none; gate G4.

## TOP 5 PRIORITIES
1 ARCH-SEC-001
2 SEC-INGRESS-001
3 STATE-BOUNDARY-001
4 EVIDENCE-INTEGRITY-001
5 PROVIDER-WRITE-001

## NEXT_EXECUTABLE_TASK
- task: ARCH-SEC-001
- reason: Foundational security task required by all subsequent workstreams.
- user_gate_required: false

## NOT_EXECUTED
- product tests
- runtime
- browser
- provider probes
