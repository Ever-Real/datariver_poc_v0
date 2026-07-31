# ADR-0098: Governed administrator identity profile and credential reset

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Application, Security Architecture
- Refines: ADR-0031, ADR-0038, ADR-0046

## Context

The administrator user table already exposes Workspace membership summaries, Role assignment,
bounded CR participation and owned-table drilldowns. Identity profile fields and credentials remain
canonical in the configured OIDC provider, so changing only the local projection would create
false state. Conversely, exposing a generic identity-provider administration proxy would expand
the browser and application trust boundary beyond the requested user operation.

Administrators need to correct a managed human user's name, email, department and job function and
to recover access with a temporary password. The operation must not expose a password read path,
store credential material, mutate service identities or fabricate a general activity/audit feed.

## Decision

1. The application exposes only subject-bound, typed profile read/update and temporary-password
   reset commands. There is no generic Keycloak URL, document or action pass-through.
2. The target must be an active, unexpired human Workspace member whose issuer matches the configured
   OIDC issuer. Service accounts and external/unmanaged identities fail closed.
3. Profile reads require the existing eligible-human-administrator read boundary. Profile updates
   and password resets require `admin.manage`, current mutation assurance, a quoted membership
   `If-Match`, an `Idempotency-Key`, an eligible human administrator and the existing Workspace lock.
4. Keycloak remains canonical for first name, last name and email. After a provider update, the
   application reconciles the local subject display/email projection and the Workspace department/
   job-function projection through one fixed `SECURITY DEFINER` function. The function independently
   rechecks transaction-local context, administrator eligibility, target status and optimistic
   membership version and grants the application execute-only access.
5. The provider call precedes the local projection commit. If the local transaction fails, a retry
   with the same requested state safely reconciles the projection; the response never claims atomic
   distributed commit.
6. Password reset accepts exactly one bounded temporary secret, sends it only to Keycloak, marks it
   temporary and revokes the target's existing sessions. The raw password and any derivative are
   excluded from request hashes, database state, outbox/audit payloads, logs and responses. A
   repeated idempotency key reports the originally completed reset and does not rotate again.
7. The Admin UI labels platform authorization as **data·screen access Role**, distinct from the
   business job function. Its activity view uses only the existing item-authorized CR participation
   and owned-table APIs and explicitly does not represent a complete audit log.

## Consequences

- Administrators can update managed human profile projections and issue temporary password recovery
  without receiving a credential-read capability or a generic IdP administration surface.
- A provider-success/local-failure window can temporarily leave the projection stale, but a retry
  is deterministic and no local state is falsely committed before the provider accepts the change.
- Resetting a password terminates current sessions and requires the user to change the temporary
  password at the next login.
- Alembic `0083` adds only the fixed profile-projection function and its execute grant. It adds no
  credential, session or password table/column.
- Complete user activity remains an audit-product concern; this Admin view does not infer or invent
  events beyond authorized canonical relationships.
