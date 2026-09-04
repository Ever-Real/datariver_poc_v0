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
be satisfied by an ordinary `RESUME`/`REFRESH` run. Its forward-only execution states are
`CLAIMED_X`, `SUCCESSOR_BOUND_Y`, and `COMPLETE_Y`. The original request-to-X claim remains
immutable; a separate immutable successor receipt binds the same request and X to Y.

The recapture is bound to the current desired snapshot X. It performs a fresh provider capture and
requires the resulting canonical identity Y to differ from X. No change is a typed, non-promotable
failure; the Product never manufactures a successor identity. A changed Y uses the existing
verified immutable evidence path. The desired-head X-to-Y transition and request/X-to-Y successor
receipt commit in the same PostgreSQL transaction. A failed transaction can leave verified
immutable Y evidence for idempotent replay, but cannot expose Y as the desired head without its
execution binding. X, all X receipts, active graph LKGs, semantic pointers, accepted state, and
persistent volumes remain unchanged.

On restart, an unbound claim whose desired head is still X remains an explicit recapture. A bound
claim whose desired head is Y enters ordinary receipt-driven `RESUME` for Y while retaining the
source-correction execution identity in scheduler evidence. Source(Y) and every READY projector(Y)
are reused; PENDING, RUNNING, or FAILED projectors(Y) continue their owned receipt lifecycle. A
desired head different from both the claimed predecessor and its bound successor is a typed
execution conflict and is never guessed or adopted.

Product 7c created one pre-contract crash window in which verified Y and its READY Source receipt
were durable before a successor-binding receipt existed. Forward recovery may append the missing
binding only when one exact scheduler `SOURCE_CORRECTION_RECAPTURE` failure for the same request/X
is durably classified as `K9_V2_SOURCE_RECEIPT_INVALID` and the live Y Source receipt is READY.
This bounded legacy adoption does not modify X, Y, their receipts, or the desired head. Any other
unbound X/Y shape fails closed.

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
environment and is not written to the target-owned runtime environment. Before successor binding,
a terminal recapture failure remains a no-op for the same request. After binding, the Y-resume
phase is a distinct scheduler identity extension (`successor_source_snapshot_id=Y`), so the older
recapture failure cannot terminate it. Once that bound phase completes, replay is a no-op. A new
explicit request is required for a different provider correction.

No schema reset, receipt deletion, source mutation, Neo4j cleanup, LKG promotion on failure,
timeout widening, fuzzy identity, authorization widening, MCL change, PREP-only persistence path,
or parallel V3 lifecycle is introduced.
