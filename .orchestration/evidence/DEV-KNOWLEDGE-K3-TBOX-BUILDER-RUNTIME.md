# DEV Knowledge K3 minimal T-Box Builder runtime evidence

Date: 2026-08-19 KST
Authoritative runtime: Node POC
Authoritative worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`
Product SHA: `01e02acb9c75d52e11ff5fbb61c09e88146cfa49`
Deployed OCI revision: `01e02acb9c75d52e11ff5fbb61c09e88146cfa49`

## Scope and status

- Knowledge K0/K1/K2 and the completed Chat Router stayed frozen.
- This slice closes only the existing XYFlow-based typed T-Box editing path.
- K3 status: `COMPLETE_RUNTIME_VERIFIED`.
- Knowledge overall remains `PARTIAL`; K4 is next after the bounded canonical security-grade compatibility gate. K5 through K9 were not started by this slice.

## Product behavior

- Draft authors can add, edit, delete and drag Classes and Relations on the existing dark-grid canvas, then zoom, fit and explicitly lock/unlock interaction.
- Class state preserves stable ID, canonical/display name, aliases, description, parent and typed properties.
- Relation state preserves stable ID, label, source/target, direction, cardinality, aliases, description, provenance and typed properties.
- Class/Relation properties preserve bounded datatype, unit, required and single/multi cardinality semantics.
- The existing Draft/version/CAS primitive remains the authority. Server-side semantic validation and atomic rollback cover duplicate IDs/names, inheritance cycles/missing parents, missing or dangling endpoints, invalid Domain/Range, datatype/cardinality and duplicate Relations.
- The AI-source badge/provenance rendering contract exists, but this slice created no fake AI proposal and performed no LLM proposal flow.
- Cypher text remains a bounded, non-executing authoring representation. Arbitrary raw Cypher is rejected and never passed through to Neo4j.

## Source validation

- Focused `GraphBuilder` tests: 27/27 PASS.
- Focused Node POC live tests: 31/31 PASS.
- Node POC full serialized suite: 107/107 PASS.
- Frontend full single-worker suite: 87 files, 616/616 PASS.
- Lint: PASS.
- Typecheck: PASS through the production `tsc -b` build.
- Production POC build: PASS; the existing Vite chunk-size warning remains backlog only.
- Compose no-interpolate render: PASS.
- `git diff --check`: PASS.
- Product image OCI revision equals the exact 40-character Product SHA. Web health is `ok` at `http://127.0.0.1:39083`.

## Browser/runtime E2E

One explicitly disposable DEV Draft named `K3 DEV TBox E2E 20260819` was used.

1. The inspection Admin created `Person` and `Asset` Classes, defined an inheritance parent, edited their fields and removed a temporary Class.
2. A temporary inheritance cycle produced a visible validation warning and disabled save; removing the cycle restored a valid Draft.
3. The Admin created and edited `OWNS`, configured its exact source/target, bidirectional direction, many-to-many cardinality, aliases and description, then removed a temporary Relation.
4. A Relation property `confidence` preserved FLOAT, MULTI, required, unit and aliases through save and hard reload; a temporary property was removed.
5. Dragging changed persisted node positions while unlocked. Locking prevented the same drag; unlock, zoom and fit remained usable.
6. Arbitrary `MATCH (n) DELETE n` input produced a localized validation error and disabled save without any graph execution.
7. A hard reload restored the same Classes, Relation, properties, positions and version.
8. A two-tab real-browser stale-CAS conflict preserved the stale editor's input and displayed the localized conflict guidance.
9. Desktop and 390 × 844 mobile layouts kept the canvas, inspector, property list and actions reachable.
10. The disposable Draft was set to `DISCARDED` through the Product UI. No hard delete or direct Neo4j cleanup was performed; retained history identifies it as validation data.

## Authorization and security negative

- The positive browser lifecycle used the preserved inspection Admin session; its password, credential and account state were not changed.
- Current request-time Knowledge route tests cover no-grant and mutation authorization negatives. This evidence does not claim a second lower-role browser login.
- Stale CAS is server-authoritative, arbitrary Cypher is non-executable, and invalid semantic state cannot be persisted.

## Independent validation

- Requested/effective model: Gemini 3.1 Pro High (High), read-only Node POC reviewer.
- The first launcher attempt was denied before execution by its command-permission boundary and produced no Product claim or mutation.
- One corrected read-only retry verified the authoritative root/branch/HEAD, clean worktree, Node POC command, focused 27/27 and Node 107/107, and returned `PASS`.
- The reviewer reported an image digest rather than the OCI revision label; that label claim was discarded. Product/OCI exact equality is coordinator-owned evidence above.
- The reviewer's broad attribution of the localized stale-CAS browser result to unrelated Node coverage was also discarded; the accepted stale-CAS evidence is the coordinator's actual two-tab runtime flow.

## Remaining backlog

- `KNOWLEDGE_SECURITY_GRADE_CANONICAL_REALIGNMENT`: bounded K4 entry gate; align legacy Knowledge labels to `normal < credential < restricted` without a new grade framework or silent history rewrite.
- `FRONTEND_ASYNC_TEST_PARALLEL_FLAKINESS`: non-blocking; the single-worker 616/616 suite is the stable baseline.
- `NODE_PROVIDER_PROBE_PARALLEL_FLAKINESS`: non-blocking; focused/serialized provider probes remain authoritative.
- `CHANGE_MONITORING_LEDGER_SURFACE_RELOCATION`: unchanged `NEXT_SLICE_FEEDBACK`; it did not interrupt K3.

## Overengineering check

```text
new tables       0
new dependencies 0
new services     0
new containers   0
new queues       0
new workers      0
new frameworks   0
new capabilities 0
```

No push, publication gate, PREP/OPS mutation, migration, new graph framework, K4+ Product mutation or generic IAM/ACL work was performed.
