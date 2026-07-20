# ADR-0025: Operator security modes and stable authentication renewal

- Status: Accepted
- Date: 2026-07-20
- Refines: ADR-0009, ADR-0024

## Context

DataRiver uses a Workspace as the tenant and security scope for membership, ABAC decisions,
classification policy, cache keys, canonical records and PostgreSQL RLS. A development installation
may have only one Workspace and does not need to ask users to switch it manually, but removing the
Workspace identifier would remove a security boundary rather than simplify presentation.

The portable identity profile also supports hardware WebAuthn for high-risk mutations. Some
internal-network deployments do not permit USB devices or do not want to operate WebAuthn. A UI-only
hide would be misleading because the API could still recognize WebAuthn assurance, while silently
downgrading those operations to an ordinary password would weaken ADR-0009.

Separately, silent OIDC access-token renewal updates the in-memory token and verified profile. The
web application previously rebuilt its `ApiClient` whenever that token changed. Feature effects
depend on the client identity, so a normal renewal triggered redundant screen-wide reads and visible
flicker even though the authenticated session remained valid.

## Decision

Keep Workspace mandatory as an internal security scope. Add the operator-owned
`WORKSPACE_SELECTION_ENABLED` setting. When it is `false`, `/auth/me` tells the browser to hide the
manual selector and the browser always uses the server-verified `default_workspace_id`, ignoring a
different Workspace in the URL. A missing default fails closed before workspace-scoped screens are
rendered. ABAC, request headers, cache scope and RLS continue to use the selected default exactly as
they do in multi-Workspace mode.

Add the operator-owned `OIDC_HARDWARE_WEBAUTHN_ENABLED` setting. When it is `false`, DataRiver does
not expose enrollment or initiate WebAuthn step-up and its token verifier does not classify even an
otherwise matching ACR/AMR claim as `HARDWARE_WEBAUTHN`. High-risk operations that require that
assurance remain denied. The setting does not create a password fallback, remove credentials from
the external IdP or change the independently governed maker-checker fallback scope.

Both controls are process/deployment configuration, not browser-editable administrator records.
Allowing the same signed-in administrator to lower the assurance gate that protects an intended
mutation would be a privilege-escalation path. Changing either setting therefore requires access to
the deployment configuration and a controlled API process restart. A future runtime control would
require an independently approved maker-checker command, durable audit, reauthentication and
rollback design.

Keep one `ApiClient` instance for the application lifetime. It reads the latest token, Workspace and
renew callback through stable references at request time. Token renewal therefore does not retrigger
feature loading effects; a committed Workspace change still remounts workspace-scoped feature state.

## Consequences

- Single-Workspace installations remove a confusing user choice without weakening tenant isolation.
- Workspace selection is not Admin-only. Every verified user receives only their server-selected
  default and can switch only when deployment policy exposes the selector and server membership
  authorizes the requested Workspace.
- Disabling WebAuthn can make direct high-risk administration unavailable. Operators must accept
  that loss of functionality or implement a separately governed replacement; ordinary password
  login is not an equivalent replacement.
- Keycloak or another IdP may still contain WebAuthn credentials and flows, but DataRiver neither
  invokes nor trusts them while its capability is disabled.
- Silent token renewal updates request credentials without refreshing every feature screen. A true
  session-renewal failure still returns to the explicit sign-in state.
