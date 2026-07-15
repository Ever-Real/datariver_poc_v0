# ADR-0004: Immutable KG canonical model and replaceable projections

- Status: Accepted
- Date: 2026-07-14

## Decision

Store ontology, changesets, provenance and immutable node/edge releases canonically in PostgreSQL/object snapshots. Start with a PostgreSQL adjacency query adapter; support Apache AGE and Neo4j Community only as rebuildable, private read projections.

## Rationale

This prevents graph-engine licensing/edition limits from controlling correctness, authorization, backup or version history. It also enables deterministic rollback and projection drift detection.

## Consequences

Publishing has an explicit projection-build/verify/activate phase. Direct Bolt access and raw Cypher APIs are prohibited. Projection-specific performance is optimized without changing release semantics.
