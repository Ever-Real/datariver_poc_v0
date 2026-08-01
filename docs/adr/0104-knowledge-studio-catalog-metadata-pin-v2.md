# ADR-0104: Knowledge Studio Catalog metadata pin V2

- Status: Accepted
- Date: 2026-08-01
- Owners: Product, Data Architecture, Knowledge Platform, Security Architecture, Operations
- Refines: ADR-0074, ADR-0099

## Context

The durable Catalog Proposal job in ADR-0099 pins an Asset identity, source/projection versions and
selected field paths. That V1 shape is sufficient to fence identity and projection drift, but it
does not give the Schema Assistant the authorized table/column descriptions, types, tags and terms
that users selected in the Catalog UI. Sending browser-assembled metadata would make the client an
authority and would permit a stale search result to influence provider input.

The provider is not a canonical store. The worker cannot safely receive DataHub credentials or
claim that it observes provider-current metadata. PostgreSQL remains the job and pin system of
record, and old V1 jobs must remain readable and executable during rolling deployment.

## Decision

### Server-owned optimistic fence

The Catalog detail response includes an opaque `selection_fingerprint` computed from the current
authorization-pruned detail. A Catalog Proposal request echoes it as
`expected_selection_fingerprint`. The browser does not recompute the value and sends no metadata.
The API reauthorizes the Workspace, mutable Draft, `kg.edit`, Catalog Asset, classification and
source policy, reloads the current detail and compares the exact fingerprint. A missing, stale or
forged fence returns `409 CATALOG_PROPOSAL_SELECTION_STALE` before job or outbox creation.

### Immutable V2 source document

After the fence succeeds, the server selects at most 100 unique field paths and orders field
metadata to match those paths exactly. It creates `KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2` with:

- exact Asset ID/name/type/classification, raw source version and local projection source version;
- optional platform/database/schema/domain, at most 100 asset tags and glossary terms (255
  characters each), and an optional 1,000-character asset description with truncation evidence;
- one metadata item per selected path, in the same order: path (2,000), logical/native type (500),
  description (1,000 plus truncation evidence), up to 20 tags and 20 terms (240 each plus
  truncation evidence);
- `metadata_fingerprint`, the SHA-256 of canonical UTF-8 JSON excluding that field; and the
  existing `source_pin_hash`, the SHA-256 of the complete immutable document.

The full document is at most 65,536 UTF-8 bytes. The exact rendered provider prompt is at most
4,000 characters. Oversize input fails during enqueue with an instruction to select fewer fields;
metadata is never silently dropped. V1 is the exact legacy unversioned shape. V2 has an exact key
set; unknown versions and extra fields fail closed.

### Worker and projection boundary

The worker parses the stored document and revalidates its exact shape, bounds, path/metadata order,
metadata fingerprint and full source-pin hash. Database command/guard functions also enforce those
constraints and compare the pinned Asset name/type/classification/projection source version and
selected paths with the current local Catalog projection.

This is an enqueue-time immutable provider metadata snapshot plus worker-time local projection
drift/hash validation. The worker does not call DataHub and does not claim to detect current
provider description/tag/term changes before the next governed Catalog synchronization. When sync
advances the local projection source version, preflight fails closed as stale. Provider credentials,
rows, URNs and queries are absent from the pin and browser response.

### Compatibility and rollback

Revision `0086` replaces only the existing PostgreSQL command/guard function definitions; it adds
no table, column, role, RLS policy or grant. Functions are executed as separate asyncpg-safe
statements. V1 and V2 jobs remain accepted after upgrade. Downgrade first refuses while any V2 row
exists, requiring explicit reconciliation; only a clean downgrade restores the exact V1 functions.
The canonical initial migration installs the same final V2 function definitions deterministically.

## Consequences

- Catalog Proposal Cypher can use real authorized descriptions, types, tags and terms without
  trusting browser metadata.
- Search/detail may expose up to 1,000 bounded field entries for selection, while a job pins at
  most 100.
- Large selections fail visibly rather than producing partial or fabricated schema.
- Existing V1 queued and historical jobs remain compatible.
- Provider-current drift remains bounded by governed Catalog sync; it is not overstated as a live
  worker check.

## Verification

- Unit tests cover V1/V2 strict union, every numeric bound, order/uniqueness, truncation evidence,
  canonical fingerprints, full hashes and prompt-size rejection.
- HTTP tests cover the opaque fence, missing/stale/forged rejection and zero job/outbox side effect.
- Worker/store tests cover exact V2 decode and local projection/source-version/hash drift.
- Isolated PostgreSQL tests execute `0085 -> 0086`, downgrade refusal with V2 rows, clean
  `0086 -> 0085` and re-upgrade, including direct invalid-pin and stale-projection negatives.
- The canonical migration is generated twice with an identical hash; Ruff, strict mypy, static
  verification, TypeScript, ESLint, focused tests and production build remain required.
