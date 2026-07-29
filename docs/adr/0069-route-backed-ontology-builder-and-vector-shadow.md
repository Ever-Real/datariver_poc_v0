# ADR-0069: Route-backed ontology builder, durable ingestion and vector shadow

- Status: Accepted
- Date: 2026-07-29
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0043, ADR-0058, ADR-0059, ADR-0060, ADR-0061, ADR-0062

## Context

Knowledge Studio has a governed Step 1 Draft, A-Box binding/pre-flight model and immutable
schema/mapping publication path, but the current Step 2 canvas is deliberately non-persistent.
Enterprise authors need a route-recoverable modal, a bidirectional schema editor, reviewable LLM
and document proposals, durable instance ingestion and vector search preparation without making
browser state, generated Cypher, a model provider, Airflow or Neo4j canonical truth.

PDF, DOCX and XLSX are the approved source profiles for schema inference. Legacy DOC and XLS are
excluded because their parser and containment contracts are not approved. Large A-Box sources
cannot be processed in the request lifecycle. Text embeddings for GraphRAG must not create a second
unversioned fact store or bypass classification/provider policy.

## Decision

### Route-backed modal

The Create/Edit Studio is rendered as a focus-trapped full-screen modal inside the persistent
Knowledge application shell. Its URL continues to carry the typed Draft and step route. Refresh,
back/forward navigation and deep links therefore recover the same server Draft, while closing the
modal returns to Registry and removes only Knowledge Studio route parameters.

The modal does not own canonical state. Step 1 recovery remains subject to ADR-0059 and Step 2/3
state is read from PostgreSQL after every navigation or security-epoch change.

### Bidirectional T-Box editing

The accepted typed T-Box operation reducer is the only semantic source of truth. React Flow nodes,
edges and the safe schema-Cypher text are projections of that reducer.

- A valid editor parse produces a candidate typed operation set. Only a successful validation and
  version-fenced server save replaces the accepted reducer.
- Invalid or incomplete text remains an editor-local buffer. The last valid canvas and accepted
  operation set stay visible and unchanged.
- Lexer/parser diagnostics include stable code, severity, line, column and bounded message. The
  editor renders line-level and summary diagnostics immediately.
- Canvas add/edit/delete emits typed operations and regenerates safe schema text from the reducer.
  User labels or relation names are never interpolated into an executable query.
- Class nodes receive a server-owned deterministic ordinal displayed as the `No.` badge. Layout,
  selection, viewport and accordion state are presentation metadata.

### Blocks and proposals

T-Box blocks are ordered, versioned Draft children with an explicit kind, integer weight `0..100`
and presentation state. Weight and ordinal determine deterministic display/evaluation order only.
An operation can mutate only an element owned by its block; duplicate stable identity or canonical
name across blocks is rejected. No weight rule silently overwrites a human-authored schema element.

LLM, PDF, DOCX, XLSX, Catalog and exact Asset Release inputs create separate proposals. A proposal
cannot change an accepted operation, Studio Release, instance release, DataHub or Neo4j.

Proposal modes are:

- `MERGE_INTO_CURRENT`: preview against the current folded graph.
- `APPEND_LAYER`: create a separate block/layer and preview there.

Merge conflicts are classified as `IDENTITY`, `KIND`, `PROPERTY`, `ENDPOINT` or `CONSTRAINT`.
The default per-conflict decision is `KEEP_ORIGINAL`. Non-conflicting proposal elements may be
accepted, while every conflicting element requires one of `KEEP_ORIGINAL`, `ACCEPT_PROPOSAL` or
`RENAME_PROPOSAL`. `KIND` and relation-endpoint conflicts can never be silently overwritten.
The UI opens a conflict-resolution dialog before acceptance when any conflict exists. Acceptance is
one-time, idempotent, ETag-fenced and revalidates source, model, classification and base hashes.

The assistant instruction is bounded to 4,000 characters and retained with the typed proposal for
author review. Canonical records retain the exact schema-assistant binding and typed proposal, but
never provider credentials, transport metadata or the raw provider response.

### Governed document profiles

Schema inference accepts only integrity-verified, actor-owned uploads with these exact profiles:

- `application/pdf`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

The 50 MiB source ceiling remains an absolute maximum. PDF keeps the existing 500-page and
five-million-character ceilings. DOCX and XLSX parsers must additionally enforce archive expansion,
entry, paragraph/table, sheet/row/cell and total extracted-character bounds before provider
egress. These are code-owned safety ceilings with deployment-configurable lower limits; a
deployment setting cannot raise the hard ceiling. DOC, XLS, encrypted archives, macros, external
links and embedded executable objects fail before model invocation.

Document parsing and model inference require a separately fenced durable proposal worker before
those source types can be enabled. The interactive LLM assistant returns a typed proposal in the
request lifecycle, rechecks the Draft version after provider latency and never applies it
automatically. Parser/model unavailable is an explicit capability failure, never an empty
successful proposal.

### Durable A-Box ingestion

Pre-flight success does not perform ingestion. An ingestion command pins the immutable Studio
Release, ontology and mapping hashes, source versions, authorization snapshot, physical adapter,
embedding binding and idempotency request. It creates a PostgreSQL job and returns `202`.

The current command contract persists `PENDING`, `RUNNING`, `FAILED` and `SUCCESS`, a bounded
percentage and stage. It also reserves lease epoch/token/fingerprint/expiry fields for the
separately deployed worker. The UI polls only while visible and while a job is non-terminal, stops
after a bounded window and resumes on visibility change or an explicit new run. Retry,
cancellation, stale handling, attempt/event evidence and worker mutation grants remain closed
until the worker contract is implemented and reviewed; the API role cannot mark a job successful.

Airflow or another approved runner may later trigger or monitor work through a purpose-bound
service identity, but PostgreSQL job and result records remain canonical. Provider or worker
failure cannot modify an immutable Studio Release or active instance release. A future successful
run creates a DRAFT changeset only; independent review and governed publication remain mandatory.

### Vector embedding shadow

A T-Box Property may opt into vector indexing only through a typed vector policy:

- `enabled=true`
- an approved text data type
- one server-owned embedding profile/version
- bounded composition mode and maximum input length

The policy is part of the immutable ontology/Studio Release hash. At queue time the server requires
every vector-target Property to have an exact mapping rule, then pins the Property/Class identity,
binding ID, source field path and exact embedding binding into the job. A future worker builds
bounded text only from those pinned mappings, rechecks classification/provider policy and stores
vector generation evidence with the Draft changeset/run. Embeddings must be finite, non-empty,
dimension-consistent and no larger than 16,384 dimensions.

Neo4j vector state is a release-scoped rebuildable shadow. Projection uses server-defined,
parameterized Cypher and a server-owned index name derived from an allowlisted adapter contract,
never from a browser label. Vector nodes include Workspace, graph, release, entity and embedding
binding/hash scope. Projection verifies entity counts, vector counts, dimensions and release hash
before recording `SHADOW_VERIFIED`.

Neo4j vectors are candidate selectors only. GraphRAG rehydrates the selected entity and properties
from the exact PostgreSQL release and reauthorizes every citation. Missing or drifted vector
evidence fails closed. PostgreSQL release content and embedding receipts remain sufficient to
delete and rebuild the Neo4j vector index.

### Managed default graphs

The metadata-lineage and glossary graphs are deterministic system-managed Assets, but neither
migration nor scheduler fabricates a published release. An active managed policy pins the exact
graph, Studio Release, source/mapping contract, System principal, schedule and classification
ceiling. Each daily trigger creates a canonical refresh run and produces a success, no-op, blocked
or failure receipt. Drift, missing policy or revocation leaves the active release unchanged.

## Consequences

- The Studio gains modal UX without losing route recovery, optimistic concurrency or the persistent
  application shell.
- Invalid editor text cannot corrupt the canvas or server Draft.
- `KEEP_ORIGINAL` prevents model suggestions from silently replacing human-authored schema.
- A-Box progress is honest durable state rather than request duration or fabricated percentages.
- Vector search is available only for reviewed typed properties and exact release/model evidence.
- DOCX/XLSX introduce new parser and decompression-bomb test obligations.
- Real provider, physical reader, Airflow and Neo4j vector acceptance remain deployment gates even
  when local source tests pass.

## Verification

- Lexer/parser/formatter/reducer round trips, invalid-buffer last-valid canvas and line diagnostics.
- Canvas-to-text add/edit/delete with stable ID/ordinal preservation.
- Block ownership/order and proposal conflict matrices with default `KEEP_ORIGINAL`.
- PDF/DOCX/XLSX profile, archive-bomb, macro/link, size and extracted-text negative tests.
- Proposal version fencing and ingestion command replay/source/auth/model pin tests; lease loss,
  retry, cancellation and crash interleavings become mandatory with the worker increment.
- Cross-Workspace, author/reviewer, domain, classification and provider-policy negatives.
- Vector policy type validation, bounded text, dimension/hash checks, Neo4j rebuild/read-back and
  canonical PostgreSQL rehydration.
- Registry/Studio route refresh/back/focus restoration and unaffected-menu regression.
