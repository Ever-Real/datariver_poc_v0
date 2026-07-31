# ADR-0099: Governed Knowledge Studio T-Box Proposal jobs

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Knowledge Platform, Security Architecture, Operations
- Refines: ADR-0044, ADR-0069, ADR-0072, ADR-0074, ADR-0083, ADR-0093
- Supersedes: the route-specific synchronous Proposal timeout bridge in ADR-0083

## Context

Knowledge Studio currently accepts a document as one multipart HTTP request, parses it in the API
process and waits for the Schema Assistant before returning a Proposal. The reverse-proxy timeout
bridge in ADR-0083 prevents an early `504`, but it does not make the work durable, observable,
cancellable or recoverable. It also bypasses the canonical Upload aggregate and persists object
storage coordinates in a Knowledge-owned source reference.

The existing `/uploads` API cannot simply be exposed to every Knowledge author. It is a
Registration operator surface protected by `registration.*` authorization. A Knowledge author
must not gain Registration authority merely to submit a source for a Draft they own.

Long-running inference cannot mutate the Draft, publish a Release or write Neo4j. PostgreSQL
remains the job and Proposal system of record, accepted object manifests remain Integration-owned,
and object storage and inference providers remain fallible external dependencies.

## Decision

### Accepted-upload ingress

Knowledge Studio receives files through Draft-scoped upload endpoints. Each endpoint first
authorizes the exact Draft, author, domain, classification and `kg.edit` action, then delegates to
the existing Integration upload aggregate through a trusted application contract. The public
`/uploads` identity and `registration.*` requirements are unchanged.

The server selects `KNOWLEDGE_STUDIO_DOCUMENT_V1`; the browser cannot select a content profile or
classification. The profile admits only PDF, UTF-8 CSV/TXT/JSON/XML/HTML and macro-free,
external-link-free DOCX/XLSX/PPTX, with a hard 10 MiB limit. Legacy DOC/XLS/PPT, unsafe XML,
encrypted or executable OpenXML content and extension/MIME mismatches fail before inference.
PUBLIC and INTERNAL accepted objects for this profile are promoted into the existing private
`knowledge-eligible` namespace.

Knowledge stores and returns only an immutable manifest pin: manifest UUID/version, actual
size/MIME/SHA-256, classification, content profile and validation evidence/configuration hashes.
Bucket, object key, presigned URL and provider object metadata do not enter Proposal job rows,
events, logs or browser job responses.

### Durable Proposal jobs

`knowledge.tbox_proposal_jobs`, `knowledge.tbox_proposal_attempts` and
`knowledge.tbox_proposal_events` are the canonical execution records. Enqueue returns `202` and is
idempotent and Draft-version fenced. Owner-scoped list/get lets the browser resume after refresh.

Document jobs pin the accepted upload manifest. Catalog jobs pin a bounded, authorization-pruned,
server-owned structured Catalog snapshot and its source version; they never persist a browser
query or arbitrary URN. Interactive free-form Schema Assistant requests stay within the bounded
synchronous ADR-0069 contract because no approved retention policy exists for raw chat input.

States are `QUEUED`, `RUNNING`, `RETRY_WAIT`, `CANCEL_REQUESTED`, `SUCCEEDED`, `FAILED`, `STALE`
and `CANCELLED`. Stages are `QUEUED`, `SOURCE_VALIDATION`, `PARSING`, `INFERENCE`, `VALIDATING`,
`FINALIZING` and `COMPLETED`. The UI derives its stepper solely from these server values. It does
not use timers or fabricated percentages.

Each job pins:

- Workspace, Draft, requester, target block and Proposal mode;
- base Draft version and folded accepted T-Box hash;
- immutable source identity, version, content and validation hashes;
- exact parser configuration and Schema Assistant binding hashes;
- requester authorization snapshot hash, request hash and aggregate pin hash.

Before provider egress and again before finalization, the worker rechecks requester membership and
authorization, Draft ownership/state/version/T-Box hash, target block, source acceptance and
classification, parser configuration and model binding. Drift produces `STALE`; cancellation
prevents finalization.

Successful finalization atomically inserts one existing `READY` TBoxProposal, marks the attempt and
job successful, appends an event and emits the outbox transition. It never applies the Proposal.
Human apply remains one-time, idempotent, conflict-resolved and `If-Match` fenced.

### Isolated worker authority

The worker uses a direct `datariver_knowledge_proposal` PostgreSQL login with `NOBYPASSRLS`, no
role inheritance and no direct table mutation grants. Security-definer functions with fixed
`search_path`, lease-token hash and lease-epoch checks provide claim, renew, fail, cancel and
finalize transitions. RLS limits reads to the exact claimed job and its pinned Draft, source,
requester and model evidence.

The worker has a dedicated service process and Redis consumer group. It may reuse the existing
read-only Knowledge object credential only because that credential has no list/write/delete
authority and its exact `knowledge-eligible/*` read scope is identical. Database credentials are
never reused. The API role cannot claim, run or mark a job successful.

Automatic retries use bounded `RETRY_WAIT`. A manual retry creates a successor job after all pins
are revalidated; terminal evidence is immutable. Queued cancellation is immediate and running
cancellation becomes `CANCEL_REQUESTED`.

## Consequences

- The API no longer waits for document parsing or provider inference.
- Browser refresh and temporary provider failure no longer lose work or create a second Proposal.
- Knowledge authors can submit Draft-scoped sources without receiving Registration operator
  privileges.
- The synchronous document- and Catalog-Proposal endpoints are retired in the UI cutover, and the
  route-specific reverse-proxy timeout bridge is removed because source bytes and inference no
  longer traverse the web proxy as one long-running request.
- Raw document excerpts, prompts, provider responses and object coordinates are not persisted in
  job control-plane data.
- Deployment must explicitly configure and start the isolated worker. Disabled or incomplete
  worker/model configuration is an unavailable capability, not a fake successful workflow.

## Verification

- API latency tests prove enqueue returns without invoking parser or provider.
- Upload tests cover every accepted format and size plus legacy, macro, external-link, unsafe XML,
  MIME/extension, classification and cross-owner negatives.
- PostgreSQL tests cover forced RLS, direct DML denial, cross-Workspace/owner invisibility,
  idempotent enqueue races, `SKIP LOCKED`, token/epoch fencing, lease recovery, cancellation,
  retry, revocation and every source/base/model drift.
- Fault injection proves READY Proposal, job, attempt, event and outbox finalize atomically.
- Response/event/log tests prove raw prompt, excerpt, bucket, object key and provider body absence.
- UI tests cover accepted upload, honest stage rendering, visibility-aware bounded polling,
  refresh resume, cancellation, retry and exact result Proposal preview.
- Ruff, strict mypy, backend tests/static verification, deterministic Alembic generation,
  TypeScript, ESLint, component tests and production build remain required.
