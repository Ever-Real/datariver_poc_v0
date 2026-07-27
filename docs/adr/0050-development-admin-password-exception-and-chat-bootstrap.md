# ADR-0050: Development administrator password exception and governed Chat bootstrap

- Status: Accepted
- Date: 2026-07-26
- Refines: ADR-0009, ADR-0010, ADR-0011, ADR-0018, ADR-0047, ADR-0048, ADR-0049

## Context

The intranet development profile intentionally disables WebAuthn by default. ADR-0047 correctly
keeps all high-risk mutations denied in that state, but this also prevents an isolated local
developer from exercising canonical System and policy administration before a physical
authenticator is available. Separately, environment-selected Chat, Embedding and Reranker adapters
cannot enter governed Chat until three immutable provider-profile versions, an active
classification policy and an active retention policy exist.

The exception must not assert fictitious hardware assurance, relax production, overwrite an
existing governed policy, hardcode a model, or make Admin write a host environment file.

## Decision

### Explicit local password exception

Add `DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED`, default `false`. Settings reject it unless all of
the following are true:

- `APP_ENV=development`;
- `ADMIN_PASSWORD_FALLBACK_ENABLED=true`; and
- `OIDC_HARDWARE_WEBAUTHN_ENABLED=false`.

When enabled, the authorization application service may replace a denial only for
`admin.manage`, only when every original denial reason is authentication-related, and only for a
fresh `PASSWORD` or `PASSWORD_REAUTH` subject. Missing, stale or future authentication time,
non-password assurance, inactive actors/resources, workspace mismatch, action denial, insufficient
clearance, owner/scope mismatch and service actors remain denied.

The resulting decision records `DEVELOPMENT_PASSWORD_BYPASS`, appends the explicit policy version
`development-admin-password-bypass-v1`, and preserves the real authentication assurance and time.
Domain events likewise record the actual assurance; they never claim `HARDWARE_WEBAUTHN`.
Only the administrator HTTP composition roots receive the flag.

### Explicit local governed Chat bootstrap

Provide an operator command, not an API or startup side effect. It reads the exact effective
runtime bindings already derived from the selected environment and requires explicit jurisdiction,
region, attestation-evidence reference, attestation lifetime, RESTRICTED-grant lifetime and local
retention values. It never chooses a model or endpoint.

Within one workspace lock and transaction it:

1. verifies two distinct eligible human administrators;
2. reuses or maker/checker-approves one exact current INTERNAL provider profile per Composition,
   Embedding and Reranker stage;
3. creates an active classification policy only when no active policy exists, enabling Chat for
   PUBLIC and INTERNAL while denying Chat for CONFIDENTIAL and RESTRICTED;
4. creates an active local retention policy only when no active policy exists; and
5. returns the three profile UUIDs.

The host wrapper writes only those returned UUIDs and disables ephemeral no-store Chat in the
operator-selected ignored environment file. Existing active classification or retention contracts
that differ cause a conflict; the bootstrap does not supersede them.

Provider attestations are short-lived fingerprints bound to the supplied evidence reference and
the exact route/provider/model/deployment identity. They are local acceptance evidence, not
production residency or zero-retention certification.

## Consequences

- Local browser E2E can exercise canonical high-risk Admin operations without a physical
  authenticator while production and non-admin actions remain unchanged.
- The exception is visible in decision/audit evidence and cannot be mistaken for WebAuthn.
- Governed Chat initialization is idempotent for the exact contract and fail-closed for drift.
- Local maker/checker bootstrap assigns the existing human Data Steward `sua.han` the additional
  `security-administrators` group and `admin.manage` action; no service account is used.
- Retention numbers passed to the command are development acceptance inputs only. They do not
  establish a production retention decision or enable archive deletion.
- This ADR does not authorize automatic startup seeding, production password bypass, active-policy
  replacement, model creation/pull, provider credential storage or Admin-to-environment writeback.
