# ADR-0006: P0 read safety and DataHub bulkhead

- Status: Accepted
- Date: 2026-07-15

## Decision

Keep PostgreSQL as the first catalog read plane while making it safe to measure at production-like
scale. Literal user search is normalized and escaped, non-empty short queries are rejected, and
active catalog rows use stored `tsvector`, `pg_trgm` and workspace/scope/order partial indexes.
Short-lived search cache keys include workspace, complete permission scope, policy version, request
shape and projection watermark.

DataHub access uses a bounded-concurrency bulkhead and retryable-failure circuit breaker. Asset
detail starts from the authorized local projection; fresh enrichment is cached briefly and a
separate bounded stale copy may be served with `stale_at` during a retryable DataHub failure.
Canonical writes and reconciliation never use stale evidence.

Chat evidence candidates are still evaluated individually by the deterministic policy engine, but
the result set is persisted as one request-scoped decision record containing the per-resource
effects and reason codes. This reduces transaction/write amplification without losing audit proof.

## Consequences

- PostgreSQL remains the read plane until the measurable P1 extraction triggers in
  `14_PRODUCTION_HARDENING.md` fail; OpenSearch is not introduced speculatively.
- `pg_trgm` is a required PostgreSQL extension owned by the migration identity.
- Cache loss changes latency only. Permission or projection changes produce a different cache key.
- Target-data `EXPLAIN (ANALYZE, BUFFERS)`, revocation timing, load/soak and DataHub contract tests
  remain production gates; index presence is not performance proof.
- Monthly audit/event partitioning is deferred until volume, retention and WORM requirements are
  approved because retrofitting partition keys changes uniqueness and maintenance semantics.
