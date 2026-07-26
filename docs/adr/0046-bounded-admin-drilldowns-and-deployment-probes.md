# ADR-0046: Bounded administrator drill-downs and deployment-owned probes

## Status

Accepted

## Context

The administrator UI already displayed per-member Change Request and owned-table counts, but it
could not show the contributing records. System Settings also labeled deployment-managed
connectors as configured while sending every connection test to a PostgreSQL/OIDC-only endpoint.
That mismatch produced a validation `422` for DataHub and Redis and encouraged clients to infer
runtime configuration.

Local development also needs representative human identities. A DataRiver membership without the
matching IdP identity is not an account and must not be presented as one.

## Decision

- A deployment-managed connection test accepts only a fixed System identifier. The API constructs
  the probe document from its current `Settings` and mounted secret references; the browser never
  supplies a URL, credential, command, or probe path.
- PostgreSQL uses fixed `SELECT 1`, OIDC verifies the API's configured JWKS trust endpoint, and
  connector probes reuse the fixed typed probe adapter. Expected availability failures return a
  bounded `UNAVAILABLE` result and never include raw exception text.
- Unsaved development YAML uses a non-persistent draft probe. A saved revision uses the existing
  revision-bound TEST route. Only the latter can create activation evidence.
- Member CR activity and owned-table lists are Workspace/subject/cursor-bound and capped at 50
  rows per request. Every returned CR or table also passes its normal `change.read` or
  `catalog.read` ABAC decision; an administrator list grant alone does not disclose the item.
- Canonical System creation requires recent hardware WebAuthn, an `Idempotency-Key`, a
  canonical request hash, a Workspace transaction lock, and one immutable outbox event.
- The local bootstrap owns three representative human fixtures only in non-production. Each fixture
  has a matching Keycloak identity, temporary first-login credential, canonical Local Development
  membership, and a distinct Data Engineer, Data Steward, or Data Analyst access profile. The
  Keycloak synchronization records the provider-assigned immutable Subject IDs in an ignored,
  bounded `runtime/identity/` state file outside the Keycloak realm-import directory before
  membership bootstrap. The semiconductor sample seed does not create those identities.
- Workspace remains the tenant/RLS/ABAC/cache boundary even when the selector is hidden. Disabling
  DataRiver WebAuthn recognition never downgrades high-risk mutations to password-only access.

## Consequences

- Connection state and connection availability are no longer conflated, and DataHub/Redis tests do
  not fail merely because they are not bootstrap systems.
- Profile drill-downs can legitimately contain fewer rows than their source page when item-level
  authorization filters records. The cursor advances over the scanned server page.
- Local demo identities are development fixtures, not production defaults. Their generated
  temporary password remains in the existing ignored secret file and is never printed.
- Removing Workspace scoping or WebAuthn would require a replacement security ADR and migrations;
  the current UI instead explains their operational purpose.
