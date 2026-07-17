# ADR-0016: Durable typed BULK registration binding

- Status: Accepted
- Date: 2026-07-17

## Context

An `ACCEPTED` upload currently proves streamed source integrity, bounded format validation and a
version-fenced promoted-byte read-back. It does not prove that a browser-supplied DataHub Aspect
document was derived from those bytes. The operator-only raw proposal route therefore cannot become
the ordinary BULK workflow.

Inputs can be large, and synchronous request-time reparsing would create object-version TOCTOU,
unbounded API latency and incomplete retry evidence. `validation_summary` is mutable manifest
metadata and is not an immutable typed-row store. The current governance aggregate and apply worker
also execute exactly one item per change request; an HTTP loop that creates many independent
requests would have partial-success and replay ambiguity.

## Decision

Upload initiation will select an explicit server-registered `content_profile`; MIME type or filename
never implies proposal capability. Existing and general-purpose uploads remain format-only and
non-executable. The first ordinary profile is limited to description updates of existing, active,
authorized dataset assets. New dataset creation and arbitrary provider documents are excluded.

Typed preparation is a durable background workflow with `QUEUED`, `PREPARING`, `READY`, `FAILED`,
`CANCELLED` and `STALE` states, a lease/fencing token, bounded progress and attempts. It consumes an
immutable acceptance receipt and streams the entire selected content profile. Partial prepared rows
are never visible before the preparation atomically reaches `READY`.

PostgreSQL will own three append-only evidence layers:

1. a validation/preparation receipt binding workspace, upload and manifest version, input and
   accepted SHA-256, provider ETag/Object VersionId when available, content-profile/parser/scanner/
   schema configuration versions, counts and a canonical result hash;
2. deterministic typed candidates binding receipt, ordinal, local asset ID, typed operation and
   normalized candidate hash without a client-selected URN, Aspect, classification or provider
   document;
3. a unique provenance binding from one candidate/hash to the created change request and item.

These records use forced workspace RLS and composite workspace foreign keys. Worker roles can claim
and append only their bounded preparation records; the API can read authorized candidates and append
the final provenance binding. Ordinary roles cannot update or delete completed receipts, candidates
or bindings. Object coordinates, multipart identifiers and raw prepared documents are not returned
by the API.

The upload/preparation worker has no DataHub credential and cannot create an executable
`ChangeItem`. Preview resolves each candidate through the authorization-pruned local catalog,
authorizes upload read plus catalog/change scope before any provider call, reads live DataHub and
performs the aspect-specific merge. A quoted opaque ETag binds workspace, upload and manifest
version, accepted object identity, preparation/candidate hashes, current target binding and provider
source/hash.

Create accepts only candidate ID, title and reason plus the exact `If-Match` and an idempotency key.
It reauthorizes and revalidates the accepted receipt, candidate, target and live provider snapshot,
then locks manifest/receipt/candidate/target and atomically persists the one-item change request,
candidate provenance, outbox and idempotency result. Classification is derived from the locked
target and any future trusted scanner floor, never from the browser-selected upload label.
Unauthorized or unresolved targets use one non-disclosing blocked result.

The initial executable unit is exactly one candidate to one item/change request. Multi-selection is
not enabled. True bulk fan-out requires a separate durable batch aggregate with per-item claim,
checkpoint, result and retry semantics; multi-item change requests remain rejected until the apply
plane has durable item checkpoints.

## Consequences and remaining gates

The ordinary BULK path becomes cryptographically and transactionally traceable to accepted bytes
without giving upload workers provider mutation authority. Correction creates a new immutable upload
and preparation result; it does not edit a READY candidate in place. The legacy raw upload proposal
route remains deny-by-default hardware-human recovery capability and is not evidence of typed parity.

Implementation requires SQLAlchemy metadata, an Alembic migration, data-model/API/security updates,
streaming parser and malicious-input limits, worker/API/UI tests and target-store conformance. An
Object VersionId or conditional-copy capability must be recorded when the production S3 target
supports it; an ETag is correlation evidence, not a substitute for full SHA-256.

Apply-time requester/policy/local-target reauthorization, provider compare-and-set or verified
single-writer serialization, malware/scanner availability, orphan reconciliation, retention/Legal
Hold integration and cross-process idempotency concurrency evidence remain production gates. No
automatic deletion or WORM export is enabled by this decision.

The first implementation slice now validates the explicit upload profile and exposes body-free
create plus bounded read/list preparation endpoints. Creation locks the manifest, performs both
upload-read and validation authorization, requires exact optimistic version and idempotency headers,
requires the accepted validation and promoted-byte SHA-256 evidence, derives the parser/schema
configuration hash server-side and converges different keys on one source/configuration job.
Responses expose progress and cryptographic evidence but no object coordinates, lease, requested-by
identity or parser payload. The parser/execution role, completed receipt, candidate API, preview and
candidate-to-change command remain deliberately disabled and require a later reviewed slice.
