# ADR-0101: Governed Knowledge source upload ingress

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Knowledge Platform, Security Architecture, Operations
- Refines: ADR-0093, ADR-0096, ADR-0099

## Context

A-Box source analysis previously used the generic `/uploads` surface. That surface correctly
requires `registration.*`, so an ordinary Knowledge author with `kg.edit` could see the Studio
workflow but could not submit its source. Relaxing Registration authorization would cross a bounded
context and grant unrelated catalog-registration capability.

Free-form A-Box requests also need the same provenance, validation, retry and review path as files.
Converting text directly into graph mutations in the browser would bypass the immutable source
snapshot and Proposal/Changeset controls.

## Decision

Knowledge exposes graph-scoped source-upload initiation/read/part/completion routes. Every call first
authorizes the exact PostgreSQL graph and `kg.edit`; the existing Integration upload aggregate still
owns multipart state, object coordinates, hashes, validation and optimistic concurrency. The generic
Registration endpoints and their `registration.*` policy do not change.

The browser supplies only a safe basename, byte size, declared MIME and SHA-256. The server derives
classification from the graph and selects `KNOWLEDGE_SOURCE_DOCUMENT_V1`; neither field is accepted
from the client. The profile admits PDF, CSV, TXT, JSON, XML, HTML, DOCX, XLSX and PPTX up to 50 MiB.
Legacy DOC/XLS/PPT, extension/MIME mismatches and active or unsafe document content remain rejected by
the existing validation worker. Only PUBLIC or INTERNAL sources enter the private
`knowledge-eligible` read namespace.

The manifest stores a nullable, server-owned `knowledge_source_graph_id`. Generic uploads keep it
NULL; graph-scoped Knowledge initiation supplies the exact PostgreSQL graph. Read, part, completion
and analysis operations require the path graph to match this binding. A workspace/graph composite
foreign key prevents an owner from replaying a graph-A upload through graph B.
The same graph identity is carried by composite manifest-to-snapshot and snapshot-to-job foreign
keys, so a privileged direct database write cannot combine an upload or snapshot with another
graph. Migration backfills the unique graph already recorded by historical source snapshots and
refuses ambiguous multi-graph history instead of selecting one.

New source-analysis jobs require an accepted, owner-matching manifest with this exact profile,
matching declared/actual size and SHA-256, a matching graph binding, and a classification within
the target graph envelope. The job separately pins the profile and accepted validation-evidence
hash; enqueue and worker preflight both recompute it before provider I/O. New-profile jobs use
`KNOWLEDGE_SOURCE_JOB_PINS_V2`, so both values participate in the aggregate pin.

For ADR-0093 compatibility, revision 0085 marks only pre-existing `FORMAT_ONLY_V1` PDFs whose
accepted validation summary, actual MIME, size and SHA-256 reconcile and whose classification is at
most INTERNAL. This `legacy_knowledge_source_eligible` flag is migration-owned and immutable; new
generic uploads cannot set it or enter analysis. Historical jobs preserve their V1 aggregate
`pin_hash` and receive the separate immutable validation-evidence pin. If an eligible pre-0085 PDF
has no prior source snapshot, its first analysis transaction locks the manifest and assigns the
path graph exactly once after rechecking owner and evidence. A concurrent request for another graph
observes that committed binding and is rejected; no upload request or generic route can select it.

PostgreSQL remains canonical; object storage and inference are fallible adapters. A worker success
creates only a typed DRAFT Changeset for human review and never publishes or mutates Neo4j directly.
Revision 0085 also advances the existing source-finalization evidence trigger from the superseded
`builtin-abac-v2` token to the active `builtin-abac-v3` token. Upgrade and downgrade each require
exactly one expected token before replacing it, so an unexpected function definition fails closed.

Natural-language A-Box input is normalized to NFC UTF-8, bounded to 100,000 characters and submitted
as a deterministic `knowledge-prompt.txt` source. It then follows the identical hash, upload,
validation, durable analysis and DRAFT Changeset path. Raw prompt text is not added to job control
rows, events or API responses.

## Consequences

- Knowledge authors no longer need Registration authority for Knowledge-owned source analysis.
- Client-controlled security classification and parser-profile selection are removed.
- File and natural-language input share one recoverable evidence chain and one review boundary.
- Revision `0085` extends the profile vocabulary, graph/legacy evidence bindings and typed job
  validation pins. Downgrade refuses while any new-profile manifest remains.
- Provider rejection remains an external failure state. The UI must display it as failure and may
  retry the durable job; it must not synthesize a successful Proposal.

## Verification

- OpenAPI proves the initiation body excludes classification/profile and bounds size to 50 MiB.
- Unit tests cover the profile formats/limit, unchanged generic 10 MiB preview, server-owned
  `kg.edit` policy, graph/owner isolation, validation evidence and optimistic completion
  headers/idempotency replay.
- PostgreSQL source-job tests use the exact accepted profile and retain owner, integrity,
  classification, idempotency, lease and RLS fences; v2 finalization evidence is rejected while
  the active v3 policy evidence completes normally.
- Frontend tests cover deterministic prompt-source creation and the initiate → multipart → validate
  → analyze sequence without sending server-owned fields.
- Migration metadata, generated baseline, data model, Ruff, strict mypy, pytest, static verification,
  TypeScript, ESLint and production build must agree before publication.
