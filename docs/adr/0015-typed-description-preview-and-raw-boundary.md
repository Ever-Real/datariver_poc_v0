# ADR-0015: Typed description preview and raw-change boundary

- Status: Accepted
- Date: 2026-07-17

## Decision

The first ordinary MANUAL metadata edit is a dataset-description-only contract anchored by the local
catalog asset ID. Preview accepts only the proposed description. The server authorizes current
catalog read and change-create scope before reading live DataHub `datasetProperties`, deep-copies the
provider document, changes only the top-level `description`, and returns a typed diff with hashes and
source metadata. The raw provider document never crosses the browser boundary.

The preview carries an exact quoted opaque ETag whose canonical input binds the workspace, path asset
ID, authorization-relevant target fingerprint, Aspect name/hash and provider source version. Create
accepts only description, title and reason plus that `If-Match`. It re-reads DataHub, then re-resolves
and share-locks the target in the same request transaction. Asset replacement, URN/scope/
classification/lifecycle drift, source/hash drift, a live no-op, malformed/non-finite provider JSON
or a lower client classification cannot become a request. Classification is derived from the locked
target, not accepted from the client. An empty description explicitly removes the field while every
other live provider field is preserved.

The generic Aspect-create API and accepted-upload raw proposal API remain only for controlled
operator/recovery use. Both require `change.raw.create` in addition to ordinary target authorization.
The action is deny-by-default, hardware-authentication-required and human-governance-only; local and
semiconductor seed bootstrap do not grant it. Ordinary Governance and BULK pages expose no raw JSON
proposal form. Accepted BULK content remains visibly non-executable until a typed content-binding
contract exists.

## Consequences and remaining gates

This contract prevents browser-selected URNs, classifications and provider documents from defining an
ordinary change. It does not provide atomic DataHub compare-and-set: the apply worker still performs a
read followed by an external write, so provider CAS or a verified sole-writer boundary remains a
production gate. A same-key retry is reauthorized and revalidates the live preview before the
governance idempotency result is read; cross-process same-key races and response-loss/source-change
semantics therefore require an actual PostgreSQL concurrency decision and test before promotion.

Column, domain, glossary-term, tag, ownership and schema edit DTOs are separate future contracts. Raw
capability possession is not evidence that those ordinary workflows are complete.
