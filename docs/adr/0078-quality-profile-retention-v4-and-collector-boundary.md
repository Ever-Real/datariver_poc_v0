# ADR-0078: Quality Profile retention V4 and collector boundary

- Status: Accepted
- Date: 2026-07-30
- Owners: Product, Data Architecture, Data Platform, Security/Governance
- Refines: ADR-0002, ADR-0006, ADR-0007, ADR-0008, ADR-0010, ADR-0039, ADR-0040,
  ADR-0077

## Context

ADR-0077 accepts a bounded DataHub Profile projection for Quality context and freshness, but Phase
1 revision `0067` deliberately implements only the Quality control plane. Phase 2 must add the
Catalog projection without changing the meaning of existing accepted retention policies or turning
DataHub into canonical business truth.

Three implementation details require an additive decision:

1. `POLICY_BOOK_V3` is an exact-set contract containing the legacy classes plus
   `QUALITY_RULE`, `QUALITY_RESULT` and `QUALITY_AUDIT`. Adding `QUALITY_PROFILE` to V3 would make
   existing valid policy payloads invalid or fabricate a retention duration that no owner approved.
2. DataHub v1.6 `DatasetProfile` is provider observation evidence, not a stable DataRiver Catalog
   projection watermark. The local Catalog projection already owns a server-resolved
   `source_version` that changes when its canonical provider projection changes.
3. A Profile collector needs DataHub read access and a narrow Catalog write capability, but it
   must not inherit API, Quality-worker, Airflow or source-database credentials. A portable default
   must not invent production concurrency, field-count, freshness, retention or key-management
   capacity.

This ADR is an additive refinement of ADR-0077. It does not replace, weaken or rewrite ADR-0077.

## Decision

### Frozen Profile adapter

Phase 2 introduces a separate typed Profile reader. It does not widen the general asset-detail
query, accept caller-supplied GraphQL or expose a generic provider pass-through.

The adapter:

- accepts only the server-resolved DataHub dataset URN;
- uses one source-controlled query and parser contract for pinned DataHub v1.6;
- reuses the existing version check, bulkhead, circuit breaker and 8 MiB response limit;
- requests only table row/column/byte counts, profiled time, `partitionSpec`, field path,
  null count/proportion and unique count/proportion;
- bounds profile count, field count, field-path length, partition ingress and numeric values;
- rejects duplicate field paths, invalid types, non-finite or out-of-range proportions,
  inconsistent count/proportion pairs and structural contract drift;
- returns sanitized `UNAVAILABLE` or `PARTIAL` state rather than truncating or treating missing
  evidence as success.

The projection may preserve a provider-declared `SAMPLE` kind as non-GX contextual evidence, but
it never requests, persists, logs, caches or returns sample rows or sample values. Distinct-value
frequencies, top/example values, min/max/mean/median/stdev, quantiles and histograms are outside
this contract. A sampled Profile is never promoted to `FULL` and no Profile produces a GX
pass/fail decision.

Raw partition or query text exists only as bounded parser ingress. For `PARTITION` and `QUERY`, the
parser may create an HMAC-SHA-256 fingerprint using a deployment-owned `file:` key and bounded key
ID. It discards the raw value before constructing the application DTO. Raw text and unkeyed
digests are prohibited in storage, caches, logs, traces, errors and API responses. `FULL`, `SAMPLE`
and `UNKNOWN` carry no provenance key or fingerprint.

### Canonical Profile source watermark

The Profile projection uses the current local `catalog.assets_projection.source_version` as its
canonical source watermark input. It does not invent a provider cursor from the Profile payload and
does not trust a browser- or collector-supplied source version.

After resolving the active local asset, the application computes
`source_watermark_hash` with the existing canonical JSON SHA-256 function over:

- contract `CATALOG_ASSET_SOURCE_WATERMARK_V1`;
- workspace ID;
- local asset ID;
- the exact server-read Catalog `source_version`.

The snapshot stores both `asset_source_version` and the resulting hash. The fixed projection
function revalidates the current local asset and exact source version before writing. A missing,
blank, changed or stale source version makes collection unavailable; it is not replaced with a
DataHub timestamp or normalized payload hash.

The immutable snapshot identity includes workspace/local asset, profiled time, normalized kind,
provider contract/query/config hashes, this source-watermark hash, normalized allowlisted payload
hash and any keyed provenance. Re-observing the same identity may advance only
`last_observed_at`. Changed metrics, source version, contract/configuration or HMAC key lineage
creates a new snapshot identity.

### Additive retention contract

`POLICY_BOOK_V3` remains frozen and valid for all Phase 1 Quality evidence. Phase 2 adds:

```text
POLICY_BOOK_V4 = POLICY_BOOK_V3 + QUALITY_PROFILE
```

V4 remains an exact-set contract. It requires an explicitly approved `QUALITY_PROFILE` class rule;
the migration and portable source do not choose or backfill its duration.

- Existing V3 policies and Phase 1 rows remain valid and readable.
- Existing Phase 1 `QUALITY_RULE`, `QUALITY_RESULT` and `QUALITY_AUDIT` creation may resolve against
  a valid active V3 or V4 policy.
- New Profile projection requires a valid active V4 policy and exact `QUALITY_PROFILE` binding.
  Under V2/V3 or a missing active policy, Profile collection is unavailable.
- Policy ID, policy number, policy hash, basis time, deadline and Legal Hold generation/hash are
  pinned into every Profile snapshot. Column metrics inherit the exact binding through a composite
  foreign key.

The only resource Legal Hold combination for the new class is:

```text
QUALITY_PROFILE <-> PROFILE_SNAPSHOT
```

Workspace/subject holds continue to follow the governed retention semantics. Resource holds with a
different type/class pairing fail closed. The additive migration creates the canonical empty-set
Legal Hold generation genesis for `QUALITY_PROFILE` once per existing workspace, and the normal
workspace bootstrap creates it for new workspaces. No component may fabricate a non-empty hold,
generation or policy binding.

No Profile row has a physical-delete, TTL, object-lifecycle or overwrite path. A future purge
requires the existing retention control-plane protections and a separate accepted implementation.

### Catalog projection tables and write boundary

Phase 2 adds two forced-RLS Catalog tables:

- `catalog.asset_profile_snapshots` stores local asset/source-version binding, deterministic
  identity, `FULL/SAMPLE/PARTITION/QUERY/UNKNOWN`, `COMPLETE/PARTIAL`, profile/observation/staleness
  times, nullable non-negative table metrics, bounded provider and provenance hashes, inherited
  target classification/System/Domain scope, and exact `QUALITY_PROFILE` retention/hold evidence.
- `catalog.column_profile_metrics` stores one bounded field path per snapshot plus nullable
  null/unique counts and fixed-precision proportions. Each metric has an explicit availability
  flag, and the child inherits classification, target-scope and retention/hold evidence through a
  composite foreign key.

The tables are a rebuildable Catalog projection, not a Quality result ledger and not a copy of raw
DataHub responses. Every foreign key is workspace-scoped and uses `RESTRICT`.

Ordinary application and collector roles receive no direct `INSERT`, `UPDATE` or `DELETE` grant on
either table. The only write path is a fixed, source-controlled `SECURITY DEFINER` Catalog
projection function with a pinned `search_path`. It validates the authenticated workspace,
service-only `catalog.profile.collect` authority, current asset scope/classification/lifecycle and
source version, V4 retention binding, typed hold binding, normalized metrics and deterministic
identity. It inserts an immutable snapshot and its child metrics atomically, or advances only
`last_observed_at` for an exact identity replay.

The function must not accept a URN, SQL, GraphQL, arbitrary JSON provider response, raw partition
text, policy deadline or authorization result as caller authority. Direct DML and cross-context
Quality writes are prohibited.

### Disabled-by-default one-shot collector

The `catalog-profile-collector` is a separately deployed, disabled-by-default one-shot process. It
uses a dedicated OIDC service Subject, the service-only `catalog.profile.collect` Action and a
separate NOBYPASSRLS database role. It may receive the least-privilege DataHub read token and
Profile HMAC key, but receives no source-database credential, GX runtime, Quality write grant,
Airflow dispatch authority or general API role.

The one-shot input is a bounded server-owned local asset selection. It resolves local
asset-to-DataHub identity on the server, records only sanitized per-target status and exits with a
bounded result. Phase 2 does not introduce an always-on scan loop or an unbounded “scan all”
default. Scheduling or Airflow dispatch requires a later accepted bounded work contract.

Collection remains disabled unless the target deployment supplies and validates all applicable
inputs, including:

- pinned DataHub endpoint/release and least-privilege read token;
- explicit Profile recipe/configuration hash;
- bounded worker concurrency, maximum fields/targets and timeouts;
- positive freshness SLA;
- HMAC key ID and mounted `file:` key for PARTITION/QUERY support;
- collector OIDC identity, purpose group and dedicated database role;
- active V4 policy with approved `QUALITY_PROFILE` duration and initialized Legal Hold generation.

Missing inputs produce an unavailable capability or startup failure. Portable source supplies no
production capacity, retention duration, secret, endpoint or permissive fallback.

## Migration and verification

The additive revision must:

1. extend domain and DDL allowlists without changing V3 exact-set semantics;
2. initialize `QUALITY_PROFILE` Legal Hold genesis once per workspace;
3. create both Profile tables, constraints, indexes, forced RLS, policies and fixed projection
   function;
4. grant only the fixed function and required read paths to the dedicated collector role;
5. include tables, retention dependencies, function definition/owner/search path, RLS, ACLs and
   role membership in the semantic catalog fingerprint;
6. regenerate deterministic `0001` and verify canonical re-entry;
7. refuse downgrade while Profile rows, V4 policies/class rules or `QUALITY_PROFILE` hold evidence
   exists; an allowed empty-development downgrade restores the exact prior resolver, constraints
   and grants in dependency order.

Minimum evidence is strict static gates, parser/contract negatives, PostgreSQL 17 blank and upgrade
paths, exact V3/V4 policy validation, typed-hold mismatch rejection, genesis idempotency,
service-role positive/negative RLS and grant tests, immutable replay tests, oversize/contract-drift
tests and representative latest-Profile `EXPLAIN (ANALYZE, BUFFERS)`.

## Consequences

- Existing Phase 1 V3 policies remain valid while Profile retention requires an accountable V4
  decision.
- DataHub remains canonical for provider observations; PostgreSQL owns a bounded, rebuildable,
  authorization-protected projection.
- The local Catalog source version supplies a deterministic DataRiver watermark without inventing
  an unsupported DataHub cursor.
- The frozen adapter and fixed database function prevent generic GraphQL and direct-DML expansion.
- Deployments missing identity, capacity, freshness, retention or key-management inputs expose
  honest unavailability instead of unsafe defaults.
- Scheduled Profile collection, distribution statistics and GX evaluation remain outside Phase 2.
