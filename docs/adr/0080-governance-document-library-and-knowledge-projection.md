# ADR-0080: Governance Document library and knowledge projection

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Security/Governance, Data Platform

## Context

The existing Governance screen exposed policy status but did not own a versioned document
aggregate. A governance document must support safe rich text, HTML/Markdown/DOCX import,
attachments, independent approval, immutable history and future assistant evidence without making
MinIO, Neo4j or an embedding provider canonical business truth.

The platform already has PostgreSQL transaction/RLS conventions, a versioned
`datariver-filefolder` bucket, outbox delivery, an allowlisted OpenAI-compatible embedding runtime
and a Neo4j projection boundary. Reusing those ports is preferable to adding a second document
database, a browser-held object credential or a raw provider pass-through.

## Decision

### Canonical aggregate and approval

PostgreSQL owns `Document`, immutable `DocumentVersion`, one independent `Review` per version,
append-only `DocumentEvent`, attachment/object receipts and knowledge projection receipts. A
document is logically archived and is never deleted. A version moves only through
`DRAFT -> IN_REVIEW -> PUBLISHED|REJECTED`; publishing supersedes the prior published version.
The author cannot review their own version. Template versions use the same maker-checker lifecycle
and an exact published Template version may seed a new document.

The API requires a human identity, an explicit Action, a quoted aggregate `If-Match` for every
existing-aggregate command and an actor-bound `Idempotency-Key`. Forced RLS applies classification,
System and Domain scope. The dedicated projection role is a NOBYPASSRLS login with no role
membership and only the projection columns/tables required by its fixed worker.

### Content and object storage

The server accepts bounded HTML, Markdown or non-macro DOCX. It converts the input to canonical
HTML, extracts bounded plain text and stores the sanitizer policy version/hash with the content
hash. The HTML allowlist excludes executable/embedded content, inline style, event attributes and
unsafe URLs. The React viewer converts allowlisted DOM nodes to React nodes and does not use raw
HTML insertion.

Every version body, manifest and attachment uses a UUID-only key under
`governance/documents/v1/` in `datariver-filefolder`. The dedicated MinIO identity can perform only
conditional Put and exact-version Get/Head under that prefix. Writes use `If-None-Match: *`, require
a provider VersionId and verify checksum, metadata and exact-version read-back before recording the
receipt. Neither application nor worker exposes copy, list, presign or delete. Bucket versioning
is required. This is create-only application evidence, not a claim that MinIO operator/root
credentials provide regulatory WORM or Object Lock.

### Projection and retrieval

An outbox signal wakes a dedicated worker, while database-time leases remain the canonical work
claim. The worker first persists the exact HTML and manifest, then chunks published plain text,
embeds it with one activated provider/model binding and projects fixed parameterized
`Document -> Version -> Chunk` nodes to Neo4j. PostgreSQL retains the bounded vector shadow and
hash receipts; Neo4j and the embedding provider remain rebuildable projections.

The evidence API authorizes `governance.knowledge.read`, embeds the query with the same activated
provider/model binding and returns only current published chunks from active, classification/
System/Domain-pruned documents. It does not accept raw vectors, provider names, model names,
Cypher, SQL or GraphQL from the caller. The current portable vector shadow is capped at 2,000
authorized candidate chunks per request; pgvector/ANN adoption requires a separately accepted
extension, dimension and representative workload decision.

### Basic templates

The server publishes a versioned, sanitized starter catalog for policy, standard terminology and
security-guide Templates. These are product-owned blueprints, not persisted example business
records. An authorized user loads a blueprint into the editor, creates a normal Template aggregate
and subsequently updates it only through immutable versions and independent approval.

## Consequences

- PostgreSQL remains the sole lifecycle/authorization truth; object and graph receipts are
  reconciled evidence.
- Object write success followed by database failure can leave an unreachable immutable object.
  The service rejects stale aggregate versions before write, uses deterministic keys and safely
  adopts an exact replay; physical orphan cleanup is deliberately absent from this feature.
- Archive hides the aggregate through lifecycle and Action controls but preserves every DB row and
  object version.
- Production acceptance still requires target MinIO versioning/least-privilege proof, target
  embedding/Neo4j capacity and representative retrieval/load evidence. Source gates do not imply
  regulatory WORM or production SLO acceptance.
