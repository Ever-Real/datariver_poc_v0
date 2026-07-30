# ADR-0075: Knowledge domain administrator assurance boundary

- Status: Accepted
- Date: 2026-07-30
- Owners: Security, Knowledge Platform
- Refines: ADR-0050, ADR-0073, ADR-0074

## Context

Knowledge domain creation is an authoring operation, while inventory-wide rename and archive are
`admin.manage` operations. The HTTP routes shared the ordinary Knowledge Studio authorization
composition, so the explicit development password-reauth exception from ADR-0050 was never
available to the administrator mutations. The browser also reduced a typed assurance denial to a
generic error, leaving an eligible local administrator with no secure reauthentication path.

## Decision

The managed-domain list, rename and archive handlers use an isolated administrator authorization
composition. Only that composition receives the deployment-owned
`DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED` switch. Domain creation and every other Studio action
continue to use the ordinary composition and their existing `kg.*` decisions.

The exception does not authorize a stale, missing or unknown assurance. When it is enabled and the
only denial reasons are authentication-related, the API returns the typed `REAUTH_REQUIRED`
remediation so the browser can request a fresh `PASSWORD_REAUTH` token. The denied mutation is
never replayed automatically. The administrator must return, review the current row/version and
submit a new ETag- and idempotency-fenced request.

When the exception is disabled, production WebAuthn and all existing `admin.manage` policy
requirements remain unchanged. Non-authentication denials, explicit action denial, scope,
clearance, workspace, actor and lifecycle failures remain fail-closed in every environment.

The Domain management dialog renders the shared assurance notice and routes the explicit
reauthentication action through the existing OIDC provider. Raw token claims and decision details
remain server-side.

## Consequences

- Local administrators receive a usable, audited password-reauth path instead of a generic 403.
- Ordinary Knowledge authors do not gain rename or archive authority.
- Production assurance is unchanged.
- A successful reauthentication never causes an automatic write or bypasses the current ETag.

## Verification

- Authorization tests prove the development composition returns password reauthentication for
  authentication-only denials and never permits them directly.
- Route composition tests prove the switch is isolated from ordinary Studio services.
- Browser tests prove creator identity labels are human-readable and denied domain mutation
  renders the explicit reauthentication action.
