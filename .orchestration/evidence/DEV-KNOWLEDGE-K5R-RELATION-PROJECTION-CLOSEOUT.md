# DEV Knowledge K5-R — Relation Projection Closeout

## Scope and lineage

- Status: `COMPLETE_RUNTIME_VERIFIED`.
- Canonical start Product: `34af2b869d04fd96f4b9cd69f6eeed8729bafe28` — K5 `PARTIAL`, Node
  projection verified, blocker `K5_RELATION_PROJECTION_REQUIRED`.
- Product / deployed OCI: `43e74a0f4a6f696a64aa70ff8afeb681bf14c2d8` (exact).
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`; K6 was not started.

## Implementation

- Reused the approved K5 source-row/job authority, exact release/T-Box pins, K1 deterministic
  identity/provenance, request-time authorization and parameterized Neo4j writes.
- Added only the bounded Relation plan: one exact T-Box relation resolves two same-source Class
  bindings, two deterministic Nodes and one deterministic fixed-type edge with semantic relation
  identity and endpoint/version/source provenance.
- Preserved the existing single-Class Node projection path. No arbitrary Cypher, generic graph or
  ingestion framework, new persistence authority, migration, service, queue or worker was added.

## Verification

- Focused server regression: 2/2 PASS, including the prior K1/Node projection boundary and K5-R.
- Focused frontend regression: 2 files, 23/23 PASS.
- Lint, typecheck, production POC build, Compose render and `git diff --check`: PASS.
- A broad full suite was not rerun because this task explicitly required bounded K5-R validation.

## Runtime chain

- Preview: `READY`, plan `RELATION`, Node 2 / Relation 1; exact source and relation identity; Neo4j
  fixture state Node 0 / Edge 0 before confirm.
- Confirm: HTTP 201 `SUCCESS`; Node 2 / Edge 1 / duplicate 0.
- Projection: exactly two distinct endpoint Nodes and one distinct Relation; expected source and
  target Class identities and exact pinned T-Box version.
- Replay: HTTP 200; same job and evidence hash; Node 2 / Edge 1 / duplicate 0.
- Provenance: `DETERMINISTIC_ENRICHER`, exact source URN/row/hash, relation stable ID, endpoint Node
  IDs, graph/release and T-Box version all matched.
- Authorization: after immediate explicit Table-grant removal, the same disposable non-Admin
  session received HTTP 403 `KNOWLEDGE_TABLE_FORBIDDEN`; no Admin bypass was used.
- Cleanup: exact fixture Neo4j Nodes/Relation, ingestion jobs, source row, grant, core state,
  disposable subjects, credentials and sessions were removed or disabled. Post-cleanup counts were
  zero. The inspection admin remained active/login-enabled, unlocked, grade `restricted`, with its
  credential unchanged and one active session.
- The temporary non-secret DEV source manifest was removed by a Web-only recreation; Web remained
  healthy on 39083 and the running OCI label remained exact. Persistent dashboard 39090 stayed up.

## Closure

- Node projection regression: PASS.
- `K5_RELATION_PROJECTION_REQUIRED`: resolved.
- K5: `COMPLETE_RUNTIME_VERIFIED` for the bounded Node + Relation A-Box contract.
- PREP was not mutated; `PREP_EXTERNAL_ENV_CONTRACT_RECHECK_REQUIRED` remains external.
- K6: `NOT_STARTED`; it requires a separately valid entry gate.
- Complexity delta: tables 0; migrations 0; dependencies 0; services 0; containers 0; queues 0;
  workers 0; frameworks 0; authorization capabilities 0.
