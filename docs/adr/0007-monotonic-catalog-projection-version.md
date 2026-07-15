# ADR-0007: Monotonic catalog projection version

- Status: Accepted
- Date: 2026-07-15
- Refines: ADR-0006

## Decision

Replace the catalog search cache's timestamp-derived generation with one transactional,
workspace-scoped `BIGINT` in `catalog.projection_watermarks`. Every committed logical projection
batch advances the value exactly once in the same transaction as its asset and idempotency changes.
An exact replay, rejected batch, no-op seed operation or rollback does not advance it.

The current full reconciliation commits each page, so every partial page advances the projection
version. The final page advances it once together with tombstones and the `COMPLETED` sync state.
`catalog.sync_runs` remains the source of reconciliation completeness; the projection version only
identifies a committed local read-model generation.

The counter is advanced with an atomic PostgreSQL upsert. This serializes concurrent writers for
one workspace without coupling independent workspaces. Search cache keys bind the local projection
version, permission scope and policy version, so a committed projection mutation cannot reuse an
older cached result.

## Consequences

- Timestamp equality, clock skew and an unchanged `max(updated_at)` can no longer hide a committed
  local projection mutation from cache invalidation.
- The removed `(workspace_id, updated_at)` index no longer adds write cost for a watermark query.
- This is not a DataHub event cursor, source change watermark or atomic snapshot generation.
  Incremental ingestion and source-lag measurement remain separate production gates.
- The API role may select, insert and update only its workspace watermark under forced RLS. It may
  not delete, reset or decrement the value.
- Full-reconciliation pages remain incrementally visible. A future requirement for all-or-nothing
  snapshot visibility requires a separate shadow-generation design.
