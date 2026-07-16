# ADR-0009: Hardware WebAuthn and governed password fallback

- Status: Accepted
- Date: 2026-07-16

## Decision

Use a recent hardware WebAuthn authentication as the direct authentication requirement for
high-risk human actions. A signed token provides that assurance only when its ACR is in the
deployment's hardware allowlist, its AMR contains a hardware/WebAuthn reference from the same
approved issuer profile, and `auth_time` is present and recent. Generic `mfa`, OTP, password, a
numeric ACR by itself and access-token `iat` do not provide hardware assurance.

The local identity profile does not require mobile TOTP. Ordinary password login is LoA 1. A
separate conditional LoA 2 requires the WebAuthn authenticator, has zero reusable max age and emits
the `webauthn` AMR execution reference. WebAuthn registration is enabled for explicit application-
initiated enrollment but is never a default action for every user. Existing realms use an
idempotent Admin API migration that builds and verifies the complete flow before binding it;
startup realm import is not an update mechanism. The web client includes Keycloak's built-in
`basic` client scope so its official `AUTH_TIME` session-note mapper emits the real `auth_time` in
the access token; DataRiver does not infer that time from token issuance.

Password reauthentication is a separate assurance type and never silently becomes hardware
assurance. The implemented fallback is deliberately limited to the exact typed command
`WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1`, which replaces one existing workspace membership's access
document. It cannot carry an arbitrary Keycloak patch, provider request or executable command.
The request binds workspace, target membership version and canonical payload hash; requires a
different eligible human security-administrator checker; expires within five minutes; revalidates
maker, checker, target version and the two-eligible-administrator invariant; and is consumed by the
maker atomically once. Request and consume require recent password reauthentication; read and
approval accept recent password reauthentication or hardware WebAuthn. Generic password, OTP and
service-account tokens are denied.

The fallback feature is disabled by default. Enabling it is an environment decision made only after
two real eligible human security administrators and the browser `max_age=0` password-reauthentication
journey have been provisioned and tested. The direct membership update path remains
`admin.manage` plus recent hardware WebAuthn. Both paths prohibit self-access changes and use
optimistic versions, workspace advisory locking, forced RLS, idempotency and minimal outbox events.

## Rationale

A boolean strong-authentication flag loses the difference between phishing-resistant security keys,
mobile OTP and ordinary passwords. Replacing a missing `auth_time` with a refreshed access token's
`iat` can also turn an old user authentication into apparently recent evidence. Typed assurance and
exact issuer-profile mappings keep local Keycloak and future enterprise IdPs behind the same secure
application contract.

## Consequences

- Assurance claim allowlists are deployment configuration and must be contract-tested for every
  issuer. Organization-specific ACR names, RP IDs, origins, attestation roots and AAGUIDs are not
  source defaults.
- The portable local profile requires a user-verifying cross-platform authenticator. A production
  deployment that must restrict enrollment to approved security-key models additionally supplies
  and tests its attestation trust and AAGUID allowlist outside the portable source defaults.
- Policy-decision context records only normalized assurance and authentication time. Tokens, raw
  claims, WebAuthn assertions and credential identifiers are not audit payloads.
- High-risk actions reject missing, stale or implausibly future authentication times.
- The UI may initiate registration or step-up, but the backend is the final authority and does not
  automatically replay an irreversible request after authentication.
- Production onboarding requires at least two independent human security administrators and tested
  spare-key/revocation recovery before password fallback can be enabled.
- The API role may update only the access-bearing membership columns and mutable workflow-state
  columns. Approval rows are append-only and neither workflow table is deletable by that role.
- OIDC cannot distinguish an ordinary recent password login from a `max_age=0` password prompt by
  token claims alone. The maker-checker path is therefore a compensating control, never equivalent
  to hardware assurance; each target IdP browser profile must be contract-tested before enablement.
