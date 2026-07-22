# ADR-0031: Governed Keycloak identity provisioning

- Status: Accepted
- Date: 2026-07-22
- Refines: ADR-0009, ADR-0024, ADR-0026

## Context

DataRiver previously displayed verified OIDC subjects but sent every account-lifecycle operation to
an external IdP console. The bundled Keycloak deployment needs an administrator workflow that can
create both the provider identity and its canonical Workspace membership without giving the API a
Keycloak master credential or a PostgreSQL bootstrap credential. A provider-only user cannot enter
a Workspace, while a database-only subject cannot authenticate.

## Decision

Keep passwords exclusively in the IdP. Self-service password change starts a Keycloak OIDC
Application Initiated Action with fixed `kc_action=UPDATE_PASSWORD`; the DataRiver-themed provider
screen returns to the original profile. The UI receives only a capability flag, not a Keycloak URL,
and DataRiver never receives the replacement password. Non-Keycloak IdPs keep this feature disabled
unless they provide a separately reviewed equivalent.

Add an optional Keycloak administration adapter. It uses a dedicated confidential service account
limited to `manage-users`, `view-users` and `query-users`; its file-mounted client secret is visible
only to Keycloak and the API. Master/bootstrap credentials are not mounted into the API. External
enterprise OIDC deployments leave the adapter disabled unless their accountable operator explicitly
provisions and reviews an equivalent Keycloak control plane.

Creating a user requires an eligible human security administrator and recent hardware WebAuthn.
The API accepts a bounded typed profile, optional existing Workspace Role and a temporary password.
It creates a disabled Keycloak user marked with a hashed provisioning reference, sets a temporary
credential with `UPDATE_PASSWORD`, then calls a fixed `SECURITY DEFINER` database function. That
function independently rechecks the Workspace/actor context and active security-administrator
membership, reads any selected Role from canonical Workspace state, and creates a six-calendar-month
membership. Only after the transaction, outbox event and idempotency result commit does the adapter
enable the Keycloak user. Retries may resume only the same marked profile. An already enabled marked
user is treated as a response-loss retry and its password is not rotated.

The temporary password is never written to PostgreSQL, idempotency data, an outbox/audit payload or
an application log. The administrator must deliver it through an approved channel, and Keycloak
forces replacement at first login. If the database phase fails, the provider account remains
disabled and cannot authenticate; the same idempotency key may resume the operation.

## Consequences

- DataRiver can provision local Keycloak users and memberships together without becoming a password
  store or generic IdP administration proxy.
- Role assignment at creation materializes the existing reviewed Role document; a missing Role
  creates a PUBLIC, action-free least-privilege membership.
- Provider availability is a fallible dependency. A committed membership with a still-disabled
  provider account is safe and retryable; it is not reported as a completed onboarding.
- General identity edits, password-policy design, account recovery, federation and non-Keycloak IdP
  lifecycle remain IdP/operator responsibilities.
