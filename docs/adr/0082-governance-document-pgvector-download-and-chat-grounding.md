# ADR-0082: Governance Document pgvector, exact-version download and Chat grounding

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Security/Governance, Data Platform
- Refines: [ADR-0080](0080-governance-document-library-and-knowledge-projection.md)

## Context

ADR-0080 established the immutable Governance Document aggregate, create-only object receipts and a
portable JSON embedding shadow. The completed Admin workflow additionally needs browser attachment
download, database-native vector ranking, governed Dataset/Term graph edges and Chat citations.
Those additions must preserve PostgreSQL as lifecycle truth, exact MinIO object identity, existing
ABAC/RLS scope and fail-closed citation behavior.

## Decision

### Sanitization and attachment delivery

The server canonicalizes HTML with the fixed `bleach` allowlist and stores the sanitizer package
version, policy version and policy hash with every immutable version. React continues to render an
allowlisted DOM projection and never inserts server HTML through a raw HTML sink.

An authorized `attachment.download` request resolves attachment metadata through PostgreSQL RLS,
then returns a short-lived, private/no-store S3-compatible URL signed for the receipt's exact
bucket, object key and provider `VersionId`. The signer may use the browser-reachable MinIO
endpoint, but credentials, arbitrary keys, listing, copy and delete remain absent from the API.
The URL lifetime is server bounded to 60–900 seconds and defaults to 300 seconds.

### pgvector retrieval

Revision `0075` installs the PostgreSQL `vector` extension and adds a non-null
`embedding_vector vector` column beside the immutable JSON audit shadow. A dimension constraint
binds `vector_dims(embedding_vector)` to the recorded embedding dimension. Existing rows are
converted transactionally from the JSON shadow while the immutable-row trigger is temporarily
disabled inside the migration.

The worker writes identical values to the JSON and vector columns. Retrieval embeds only the
server-bounded query with the activated provider/model binding, applies Workspace, classification,
System, Domain, active-document and current-version filters in SQL, and performs exact cosine
ordering in PostgreSQL. Callers cannot provide a vector or provider identity. No ANN index or
production latency/recall claim is accepted by this ADR; representative capacity evidence must
precede a later index choice.

### Graph projection and Chat

The projection parses only author-declared, bounded references from applicability scope
(`dataset:` and `term:`) and explicit body markers (`[[Dataset:...]]`, `[[Term:...]]`). It creates a
`GovernancePolicy` node and fixed parameterized
`(GovernancePolicy)-[:GOVERNS]->(Dataset|Term)` edges. PostgreSQL content and projection receipts
remain canonical; Neo4j is rebuildable and never infers or mutates policy scope.

`POST /api/v1/governance/search/rag` exposes the same authorized current-version evidence contract
as the library evidence read. Chat Vector mode consumes that application port, merges eligible
Governance Document and Catalog evidence, and persists only citations that remain byte-for-byte
current after a final subject, provider-policy and active-version reauthorization. Superseded,
revoked, missing, cross-Workspace or forged evidence produces the governed unverifiable response
and no persisted citation.

The internal version states remain `DRAFT`, `IN_REVIEW`, `PUBLISHED`, `REJECTED` and `SUPERSEDED`
to preserve the accepted immutable storage contract. The Admin UI presents `IN_REVIEW` as
`PENDING_APPROVAL`; approval makes the document aggregate `ACTIVE` and presents its current
`PUBLISHED` version as `ACTIVE`.

## Consequences

- The PostgreSQL runtime image must include pgvector for both additive and canonical migrations.
- Exact-version download is auditable and revocable by authorization before signing, but a URL is
  usable until its short expiry; responses therefore remain private/no-store.
- JSON embedding values remain temporary audit/rebuild evidence and may be removed only by a later
  accepted migration with upgrade and rollback evidence.
- Declared concept references avoid LLM hallucination and raw Cypher while allowing deterministic
  Dataset/Term navigation.
- Target WORM/Object Lock, ANN sizing, representative retrieval/graph load, accessibility and WSL
  amd64 verification remain explicit environment gates.
