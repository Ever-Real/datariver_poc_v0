# DEV Knowledge K4 Source Proposal runtime evidence

## Scope

- Product slice: Knowledge K4 Catalog Table → structured T-Box Source Proposal.
- Product SHA: `fca4535cab544560bd06486dc363e6df0c6df27f`.
- Deployed OCI revision: `fca4535cab544560bd06486dc363e6df0c6df27f`.
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`.

## Contract

- Catalog candidates are current canonical `TABLE` identities authorized at request time by exact
  Table grant, canonical `normal < credential < restricted` grade and fixed Knowledge policy for
  non-Admin; Admin receives only the existing application-wide data bypass.
- Legacy Knowledge grades are read compatibly (`PUBLIC/INTERNAL → normal`,
  `CONFIDENTIAL → credential`, `RESTRICTED → restricted`) without rewriting history.
- Proposal output is typed `CLASS` plus `PROPERTY` data with deterministic IDs, exact Dataset and
  SchemaField URNs, source fingerprint and provenance. Apply requires current Draft/CAS, current
  provider detail and matching source fingerprint.
- Proposal/apply never writes A-Box instances or Neo4j. Existing core/CAS storage is reused.

## Source and test evidence

- Focused authorization: 7/7 PASS.
- Focused live Knowledge API: 32/32 PASS.
- Node POC full suite: 108/108 PASS.
- Frontend full serialized suite: 87 files, 617/617 PASS.
- Lint, typecheck, production POC build, Compose render, secret-literal scan and
  `git diff --check`: PASS.

## Browser and runtime E2E

- Created one exact disposable restricted Draft and reloaded it from server state.
- Catalog dialog returned 50 authorized current Tables. A current PostgreSQL Table and two exact
  Columns were selected.
- Preview returned one typed Class plus two typed Properties. The UI displayed DataHub Catalog
  provenance and the exact Dataset URN; the server persisted exact SchemaField URNs.
- Applied the Proposal to a new T-Box block, saved, hard reloaded and recovered the same graph,
  block, properties and provenance.
- Neo4j counts remained exactly 5 nodes / 3 edges before and after Proposal/apply, proving A-Box
  growth 0 for this runtime slice.
- At 390 × 844 the Studio stepper, saved state and navigation remained visible and operable.
- A no-grant Viewer saw zero Catalog assets on the current dashboard, read-only Knowledge controls,
  no create/edit action, and a direct Draft URL was denied by redirect to the authorized home.

## Cleanup and safety

- The disposable Draft was transitioned through the Product UI to `DISCARDED`; history was not
  hard-deleted and Neo4j was not manually mutated.
- All K4 disposable credentials are login-disabled with zero active sessions. The inspection
  `admin` remains active, login-enabled, unlocked and unchanged; it currently has zero sessions.
- A credential string exposed during the validation harness was treated as compromised and its
  exact disposable credential was immediately disabled. No secret value is retained here, in Git,
  or on the Dashboard.

## Independent validation

- Fresh requested/effective model: Gemini 3.1 Pro High.
- Validator recorded the authoritative root, branch and exact HEAD, independently confirmed the
  OCI label and `/healthz`, inspected K4 authorization/grade/URN/CAS boundaries and ran the current
  Node suite 108/108 with no repository mutation.
- Validator result: PASS. A stale draft report and an unrelated storage-risk statement were
  rejected by the CONTROL_PLANE and are not evidence.

## Status and complexity

- K4 Source Proposal: `COMPLETE_RUNTIME_VERIFIED`.
- Knowledge overall: `PARTIAL`; K5 A-Box Enricher / Projection is the next single slice.
- New tables 0; dependencies 0; services 0; containers 0; queues 0; workers 0; frameworks 0;
  capabilities 0.

