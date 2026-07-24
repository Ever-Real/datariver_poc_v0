# ADR 0044: Durable, pinned and fenced Knowledge source analysis

## Status

Accepted for Phase 5 implementation.

## Context

The existing PDF analysis request commits a `PENDING` source snapshot, performs object-store,
parser, embedding and model calls in the HTTP process, then locks the current graph and source and
creates a DRAFT against whichever active release and ontology happen to be current at completion.
That keeps the final write transactional, but it does not preserve the preparation decision across
provider latency. A release, ontology, provider configuration or requester's authority can change
while inference is running. A process crash can also leave an orphan `PENDING` source without a
durable attempt or recovery record.

The platform treats object storage and inference providers as fallible dependencies, PostgreSQL as
canonical business truth and Neo4j as a rebuildable projection. Large PDFs and low-resource hosts
also require work to run outside the API process with explicit resource and retry bounds.

## Decision

PDF analysis is a dedicated durable Knowledge job:

1. The API authorizes `kg.edit`, validates the accepted immutable PDF, requires PUBLIC/INTERNAL
   inference eligibility, resolves the exact governed active release or an explicit empty-base
   marker, locks the graph, selects the active ontology and stores its canonical hash, and resolves
   secret-free parser/model binding documents and hashes.
2. One transaction creates the source snapshot, durable job, `QUEUED` event, outbox event and
   actor-scoped idempotency result. It performs no external call.
3. A separate NOBYPASSRLS `datariver_knowledge` worker claims with database time,
   `FOR UPDATE SKIP LOCKED`, a random lease token whose hash alone is stored, a monotonically
   increasing epoch and an immutable attempt row.
4. The worker reads the private source and calls only the exact activated adapter contracts pinned
   by the job. Provider credentials and endpoints are resolved at runtime and never persisted in a
   job, response, event or log.
5. Before external calls and between bounded batches, the worker checks the current lease and
   cancellation state. Lease renewal and every terminal transition require the current
   token/epoch/owner/attempt tuple.
6. Successful output enters one final transaction that locks the job, attempt, source, graph,
   requester membership, pinned release and ontology. It reauthorizes `kg.edit` and verifies exact
   source, graph version, active-base, ontology/hash, parser and activated model binding equality.
   Only then does it atomically create pages, embeddings, extraction evidence, typed operations and
   a DRAFT changeset and mark the source, job and attempt successful.
7. Drift or revoked authority is terminal `STALE` and persists no proposal. A classified transient
   provider failure may enter `RETRY_WAIT` with capped backoff; expired attempts are
   `SUPERSEDED`. Queue/retry cancellation is immediate, running cancellation is requested and
   linearized at the fenced terminal transaction.
8. The terminal result hash binds the exact preparation snapshot, every parsed page hash and the
   complete sorted typed operation documents, endpoints, classification, provenance and confidence.
9. Provenance exposed outside the worker uses
   `knowledge-source:<snapshot-id>#page=<page-number>`. Private object keys remain worker-only data.

Dedicated Knowledge job/attempt/event tables are used instead of overloading the generic integration
job contract. Their state and fencing invariants are schema-enforced, their rows use FORCE RLS and
their application/worker grants are column-scoped. Legacy synchronous extraction rows remain
readable as `LEGACY_SYNC_V1`; the migration does not invent job evidence for them. Once durable
evidence exists, downgrade is refused.

## Consequences

- The compatibility analysis endpoint changes from synchronous `201` to durable `202`.
- The UI must poll a bounded status resource and cannot assume a changeset exists at submission.
- API and worker deployments gain one capability worker process, scoped database principal and
  object/model credentials. The core platform can run without it, but PDF analysis is unavailable
  unless it is enabled and ready.
- Provider latency, worker restart and cancellation are observable and recoverable without holding
  a database transaction or browser request open.
- A prepared job intentionally becomes stale if policy, graph base, ontology, source or activated
  model configuration changes; it is never silently rebound to newer state.
- Automatic governance transitions and other Knowledge/Chat/MCP capabilities remain separate
  phases.
