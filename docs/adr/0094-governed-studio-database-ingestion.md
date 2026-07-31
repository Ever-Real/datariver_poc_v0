# ADR-0094: Governed Knowledge Studio database ingestion

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Knowledge Platform, Application, Security Architecture
- Refines: ADR-0044, ADR-0060, ADR-0061, ADR-0062, ADR-0069, ADR-0092

## Context

Knowledge Studio can persist an exact Catalog Dataset reference, Class/Property mapping and
pre-flight receipt, but the current `studio_ingestion_jobs` row is only a queue envelope. No
deployment-owned batch reader claims that job, reads a physical source or creates an A-Box
Changeset. The API composition also has no approved physical source registry, so preview and
pre-flight correctly report `SOURCE_ROW_READER_UNAVAILABLE`.

Turning Catalog metadata into rows, accepting a browser-authored DSN/table/query, running a source
scan in the API request or writing Neo4j directly would fabricate evidence and break the canonical
boundary. A mutable Studio Draft is also not a sufficient ingestion contract: the worker must pin
the independently reviewed immutable Studio Release and its exact ontology and Mapping versions.

## Decision

### Deployment-owned PostgreSQL source manifest

The first full database source adapter is PostgreSQL only. An operator-owned immutable JSON
manifest maps an exact Workspace and local Catalog Asset UUID to:

- the Catalog source and projection versions;
- a connection-profile ID/version/hash and exact IP, port, database, schema and relation;
- a mounted `file:` password secret reference, read-only username and TLS mode;
- a logical field-path to quoted PostgreSQL-column allowlist;
- a stable keyset identity, row/byte/time/batch/concurrency budgets and workload hash.

The manifest body, endpoint, username and secret reference are never returned by an API or stored
in an ingestion job. The job and immutable Binding-pin children store only the non-secret manifest
identity/version/canonical hash, connection-profile identity/version/hash and workload hash needed
to detect deployment drift. The browser continues to submit only local Asset and server-returned
field identities. DNS execution is closed until a pinned resolver contract exists. The adapter
uses a read-only `REPEATABLE READ` transaction, exact-IP allowlisting, server-owned quoted
identifiers, parameterized keyset values, statement/lock/idle timeouts and bounded batches.
Missing or drifted deployment configuration is an explicit unavailable/stale result.

The same registry may provide the existing five-to-ten-row preview/probe port, but the preview
contract and full batch-reader port remain separate. Preview rows are never treated as ingestion
evidence.

### Immutable release command

The production ingestion command is graph scoped. It resolves the graph's current ACTIVE Studio
Release and pins its ontology checksum, contract/T-Box/A-Box hashes, immutable Binding and Mapping
versions, exact source references, graph/base instance Release, requester authorization hash,
manifest identity/hash and optional embedding binding. It creates one durable job, initial event,
outbox signal and idempotent response in one transaction and returns `202`.

The legacy Draft-scoped command does not create new mutable-Draft jobs. It may resolve only an
already PUBLISHED Draft to the same immutable command; otherwise it reports that schema/mapping
publication is required. Revision `0081` refuses an upgrade when any legacy
`studio_ingestion_jobs` row exists because those rows have no immutable Release, authorization,
manifest or attempt pins. Operators must explicitly reconcile those never-executable reservation
rows before the additive upgrade; the migration never invents production evidence or silently
promotes a `PENDING` row.

### Worker, mapping and result

The Studio-ingestion process uses a distinct NOBYPASSRLS, non-assumable
`datariver_knowledge_ingestion` database principal and a distinct service Subject. It does not
inherit `datariver_knowledge`, and the LLM source-analysis process cannot call Studio-ingestion
commands. A separate event-consumer group wakes the process. Until the role, Subject, manifest,
secret and workload inputs are explicitly provisioned, the capability remains disabled.

The worker receives a dedicated source-secret subtree and database credential. Its inference
composition builds an embedding-only runtime and resolves only the exact embedding secret when the
published contract contains a vector target; it never receives or resolves the Chat credential.

The application role receives only read plus fixed request/cancel/retry function execution. The worker
role receives only fixed claim/freeze/fence/renew/complete/fail function execution. PUBLIC execute
is revoked, every function has a fixed search path and neither role receives direct job UPDATE or
DELETE. Binding pins, events and vector receipts are append-only under forced Workspace RLS.
Attempt identity and lease pins are immutable while its bounded state/stage/result fields transition
only inside the fixed worker functions.

Workers claim with database time, `FOR UPDATE SKIP LOCKED`, a random lease token whose hash alone is
stored, monotonically increasing epoch and immutable attempt/event evidence. Renew, retry,
cancellation, stale and terminal transitions are fenced by the exact
job/attempt/epoch/token/worker tuple. Expired attempts are superseded before reclaim. Provider or
source failures use bounded retries; authorization, release, mapping, manifest or source-version
drift is terminal `STALE`.

Immediately before opening the source, the worker freezes one source-access deadline that fits
strictly inside its lease. Before every physical batch statement it calls the canonical database
statement fence for the exact job/attempt/epoch/token/deadline. Lease renewal does not extend an
open source-access window. The read-only source transaction and connection are closed before
terminal completion can be called.

Revision `0081` adds immutable `studio_ingestion_binding_pins`,
`studio_ingestion_attempts`, `studio_ingestion_events` and
`studio_ingestion_vector_receipts`. The job has a deferrable exact current-attempt relationship,
typed Release/ontology/base/result pins and state/lease/result/cancellation constraints.
`changesets.studio_ingestion_job_id` provides the reciprocal one-to-one result provenance and is
mutually exclusive with `source_analysis_job_id`.

Contract v1 materializes Class bindings only:

- exactly one `SUBJECT_ID` rule establishes a stable entity identity;
- `PROPERTY` rules use the fixed `IDENTITY@1` transform;
- Relationship, join, unit-conversion and arbitrary-expression mappings remain unavailable.

Each bounded source row becomes a typed node UPSERT with the released Class/Property canonical
names, graph classification envelope and provenance that identifies the immutable Binding,
Catalog Asset, source version and a hash of the row identity. Raw rows and credentials are never
persisted, logged or emitted. Duplicate entity identities are merged deterministically only when
their typed documents agree; disagreement is a validation failure.

At request, claim and finalization, the database revalidates under lock the ACTIVE Studio Release,
non-archived graph, ontology/contract/T-Box/A-Box/Binding/source/manifest hashes, base instance
Release and the requester's current active membership, `kg.edit`, classification and Domain scope.
Drift creates no Changeset or operation and terminates as `STALE`.

Success atomically creates exactly one provenance-bearing DRAFT Changeset, typed operations,
optional embedding receipts, final attempt/event/outbox evidence and the reciprocal terminal job
result. Database constraints require the same graph, ontology and base Release, forbid simultaneous
source-analysis provenance and bind job/result one-to-one. It does not publish the Changeset,
change the active instance Release or write Neo4j.

### Vector preparation

Only released text Properties with `vector_index_enabled=true` and an exact immutable
`PROPERTY` mapping are embedded. The worker composes bounded text from the pinned field, calls the
exact activated embedding binding and stores finite, non-empty, dimension-consistent embedding
receipts tied to the job, Changeset, entity and Property. Each typed receipt stores the exact
embedding-binding hash, content hash, dimension, vector hash and bounded vector document. These
receipts are preparation evidence, not a verified graph index.

Neo4j vector projection remains release scoped. After independent Changeset publication, a
projection worker may consume only matching receipts and must verify Release/content hashes,
entity/vector counts and dimensions before recording `SHADOW_VERIFIED`. This increment does not
claim that target Neo4j read-back is complete.

## Consequences

- Studio DB ingestion becomes an actual durable path instead of a permanently `PENDING` UI state
  when an approved manifest and worker deployment exist.
- Portable development remains fail closed when no physical manifest is configured; no sample or
  successful ingestion is fabricated.
- Published schema/mapping and DRAFT instance data remain separate governance stages.
- Jobs and attempts have only function-controlled state transitions; Binding pins, events and
  receipts are append-only. The aggregate has no ordinary purge or downgrade path. Worker
  production enablement remains closed until a separately approved retention and Legal Hold
  binding exists; this ADR does not invent a business retention period.
- PostgreSQL-only Class materialization intentionally supports less than the Mapping vocabulary.
  Relationship joins, CSV batch sources and additional databases require refining decisions.

## Verification

- Manifest tests cover duplicate keys, hashes, exact IP/TLS/secret/identifier validation, field
  allowlists and workload budgets.
- Adapter tests cover read-only transactions, bounded preview, keyset batches, row/byte/time
  limits, source-version receipts and sanitized provider failures.
- Worker tests cover claim/renew/reclaim, stale token/epoch, retry, cancel, crash and atomic
  typed-DRAFT finalization with no partial Changeset/Release/Neo4j write.
- PostgreSQL tests cover forced RLS, app-role mutation denial, worker least privilege,
  cross-Workspace isolation, function-controlled attempt transitions, append-only events and
  terminal immutability.
- Mapping tests cover missing/duplicate SUBJECT_ID, unsupported Relationship/transform,
  classification/source/release/authorization drift, deterministic identity and vector
  binding/dimension/hash checks.
- Frontend tests cover published-contract gating, bounded visible polling, retry/cancel/stale
  states and navigation to the resulting DRAFT Changeset.
