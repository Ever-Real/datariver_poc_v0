# ADR-0087: Development Governance Document password assurance

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Security/Governance, Application
- Refines: ADR-0009, ADR-0025, ADR-0047, ADR-0050, ADR-0080, ADR-0082

## Context

Intranet development keeps hardware WebAuthn disabled by default. Governance Document approval
also publishes the approved immutable version, so the generic high-risk policy correctly denies a
normal password session. The Governance Document HTTP composition did not receive the existing
development administrator password exception, however, and the browser consequently directed a
local reviewer to WebAuthn enrollment even though the deployment had no operator-approved physical
authenticator requirement.

The local maker-checker workflow still needs an independently authorized human reviewer, current
aggregate version, actor-bound idempotency and an auditable recent authentication time. The
development exception must not become a production downgrade or a generic password path for every
high-risk action.

## Decision

The Governance Document HTTP composition receives
`DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED` only for these high-risk Actions:

- `governance.document.publish`;
- `governance.document.archive`;
- `governance.template.activate`; and
- `governance.template.archive`.

The switch remains valid only with `APP_ENV=development`,
`ADMIN_PASSWORD_FALLBACK_ENABLED=true` and `OIDC_HARDWARE_WEBAUTHN_ENABLED=false`.
Authorization may replace a denial only when every denial reason is authentication-related and the
caller has a recent real `PASSWORD` or `PASSWORD_REAUTH` assurance. It preserves that assurance,
records `DEVELOPMENT_PASSWORD_BYPASS` and
`development-governance-admin-password-bypass-v1`, and never asserts hardware WebAuthn.

Missing, stale or unknown assurance returns the typed password-reauthentication remediation.
The browser does not expose security-key registration or step-up controls when the verified API
profile reports WebAuthn disabled. A denied mutation is never replayed after authentication; the
reviewer must return, re-read the immutable version and submit a new ETag- and idempotency-fenced
decision.

All action grants, self-approval denial, human-actor requirement, classification scope, Workspace,
RLS, lifecycle, independent reviewer, request hash and database constraints remain unchanged.
Non-development and disabled-exception deployments retain the hardware WebAuthn requirement.

## Consequences

- Mac and intranet development can complete Governance Document maker-checker acceptance without a
  physical security key when the operator explicitly enables the existing development exception.
- WebAuthn remains opt-in and hidden when disabled; an unavailable action no longer advertises an
  unusable registration path.
- The exception does not apply to Change Request final approval, Knowledge publication, Quality
  activation, retention, legal hold, erasure, Sharing publication or arbitrary administrator
  actions.
- Production assurance and target-environment identity acceptance remain open until exercised
  under the target deployment's approved policy.
