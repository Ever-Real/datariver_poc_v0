# ADR-0136: K9 source-correction successor lifecycle and glossary hierarchy validation

- Status: Accepted for implementation; PREP runtime acceptance pending
- Date: 2026-09-03
- Owners: Control Plane, Data Architecture, Knowledge Platform
- Refines: ADR-0133, ADR-0135
- Does not authorize: PREP access, automatic recapture on resume, source or receipt mutation, graph reset, LKG reset, or `origin/main` promotion

## Context

K9 V2 deliberately reuses immutable Source Snapshot X while any projector for X is incomplete or
failed. That protects expensive completed work from scheduled retry churn. It also means ordinary
`RESUME` and `REFRESH` cannot observe a provider-side correction made after Source X was captured.
Actual PREP proved this boundary with a provider glossary hierarchy self-loop: Source X remained
valid immutable evidence while its Metadata projector correctly failed closed.

DataHub also represents inverse hierarchy observations using different relationship types. Graph
relationship direction and provenance must remain provider-exact, while cycle validation needs one
canonical child-to-parent orientation to avoid treating a valid inverse pair as a cycle.

## Decision

Keep `RESUME` and `REFRESH` unchanged. Add an explicit operator option on the existing deploy
surface that creates one random bounded request identity. The request is accepted only for a proven
owned incomplete deployment whose desired Source is READY and has at least one failed projector.
PostgreSQL records an append-only, exactly-once claim for that request before the scheduler selects
`SOURCE_CORRECTION_RECAPTURE`.

The claimed request identity is also the scheduler execution identity. It is distinct from the
ordinary schedule boundary, survives process restart in the scheduler receipt, and cannot join or
be satisfied by an ordinary `RESUME`/`REFRESH` run. If a process is interrupted after the claim but
before a terminal scheduler receipt, startup continues that same claimed execution in
`SOURCE_CORRECTION_RECAPTURE`; once a terminal receipt exists, the same identity is a no-op.

The recapture is bound to the current desired snapshot X. It performs a fresh provider capture and
requires the resulting canonical identity Y to differ from X. No change is a typed, non-promotable
failure; the Product never manufactures a successor identity. A changed Y uses the existing
verified immutable evidence path and atomic desired-head transition. X, all X receipts, active
graph LKGs, semantic pointers, accepted state, and persistent volumes remain unchanged.

Projector and aggregate reads remain desired-snapshot scoped. After the head moves to Y, every
projector must produce a Y-owned READY receipt; an X receipt cannot satisfy Y readiness. Content
level no-op materialization may be reused only when it still yields a verified Y receipt. Once Y is
aggregate READY, ordinary resume/deploy returns to zero-work receipt reuse.

## Glossary hierarchy integrity

Persisted provider relationships, Neo4j relationship direction, type, and provenance are not
changed. Only the cycle-validation adjacency is normalized to child-to-parent orientation:

- `IS_A`, `INHERITS_FROM`, and `IS_PART_OF`: source to target;
- `CONTAINS` and `HAS_A`: target to source;
- `RELATED_TO`: excluded from hierarchy validation.

One-node self-loops and directed cycles of any length remain typed, fail-closed provider-data
failures before any Neo4j write or promotion. No entity name or URN is hardcoded, ignored, or
rewritten.

## Operations and safety

The operator action is `./scripts/prep39083 deploy --source-correction-recapture` after the normal
`sync` and `status` identity gates. The one-shot request is injected only into the effective deploy
environment and is not written to the target-owned runtime environment. Reusing the same request
after a terminal scheduler receipt cannot trigger another capture. An interrupted, non-terminal
execution may continue under that same identity, while a new explicit request is required for a
different provider correction.

No schema reset, receipt deletion, source mutation, Neo4j cleanup, LKG promotion on failure,
timeout widening, fuzzy identity, authorization widening, MCL change, PREP-only persistence path,
or parallel V3 lifecycle is introduced.
