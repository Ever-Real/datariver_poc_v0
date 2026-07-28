# ADR-0059: Knowledge Studio offline recovery and ETag conflict handling

- Status: Accepted
- Date: 2026-07-28
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0058

## Context

Step 1 auto-save must survive an ordinary network interruption, browser refresh and an ambiguous
HTTP response without turning browser state into Knowledge canonical truth. Concurrent sessions
using the same author identity can also write the same Draft version. Retrying a write without a
stable idempotency key or accepting a stale version would either duplicate work or silently discard
one editor's input.

## Decision

1. Draft create, auto-save and step-advance commands require an `Idempotency-Key`. Auto-save and
   step advance also require an exact quoted integer `If-Match`. The server locks the Draft row,
   compares the canonical version and returns HTTP `412 Precondition Failed` for a stale
   precondition. Ordinary uniqueness and lifecycle conflicts remain `409`.
2. A successful command and its exact response snapshot are committed with the idempotency record.
   A retry with the same actor, operation, key and request hash returns that snapshot before testing
   the now-stale version. Reusing the key with another request or actor is rejected.
3. The browser records each local Step 1 revision in same-origin IndexedDB before attempting the
   network request. The record contains only the typed Step 1 payload, Draft ID when known, ETag,
   idempotency key and timestamp. It contains no bearer token, provider credential, role, clearance,
   permission result, raw Workspace ID or raw Subject ID. A SHA-256 scope derived in memory from
   Workspace and Subject selects the queue; every replay is authenticated and authorized again by
   the server.
4. Server auto-save is debounced by 1.5 seconds and serialized. A successful save removes only the
   matching queued revision, so a newer keystroke cannot be deleted by an older response. Network
   restoration retries the same queued key. Browser storage failure is fail-closed: the UI does not
   send a recoverability-dependent write it could not first queue.
5. A `412` keeps the local payload and opens an explicit choice. “Latest version” reloads the server
   Draft and discards the local payload only after that choice. “Overwrite with my changes” first
   reads the latest ETag and submits the preserved typed payload with a new idempotency key and that
   ETag. There is no unconditional force-write or version-check bypass.
6. IndexedDB is recovery evidence, not canonical state and not an encryption boundary. It is
   removed after confirmed persistence or explicit reload/discard. Browser profile deletion,
   storage eviction, device loss and compromised same-origin script remain outside the application's
   absolute durability guarantee; the UI and acceptance report must not claim otherwise.

## Consequences

- PostgreSQL `knowledge.studio_drafts` remains the only durable business Draft.
- `localStorage` and `sessionStorage` remain prohibited for Drafts and security context.
- Authentication/security-epoch changes remount Studio. A matching queued command can replay only
  after the new request context passes membership, ABAC, RLS and source-version checks.
- Future shared-editor policies may broaden RLS only through a separate decision. This ADR's 412
  and recovery contract already supports concurrent sessions without changing current author-only
  visibility.

## Verification

- OpenAPI contract tests for required idempotency and `If-Match`, response ETags and 412 mapping.
- Repository tests for exact replay, changed-request rejection and stale-version failure.
- Component tests for debounced create/update, queue-before-send, reload recovery, online retry and
  both explicit 412 resolution choices.
- Static checks that no token, role or raw authorization context enters browser persistence.
