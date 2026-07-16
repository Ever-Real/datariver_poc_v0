# ADR-0009: Hardware WebAuthn and governed password fallback

- Status: Accepted
- Date: 2026-07-16

## Decision

Use a recent hardware WebAuthn authentication as the direct authentication requirement for
high-risk human actions. A signed token provides that assurance only when its ACR is in the
deployment's hardware allowlist, its AMR contains a hardware/WebAuthn reference from the same
approved issuer profile, and `auth_time` is present and recent. Generic `mfa`, OTP, password, a
numeric ACR by itself and access-token `iat` do not provide hardware assurance.

The local identity profile does not require mobile TOTP. It emits the AMR claim but remains
fail-closed for high-risk actions until an explicit WebAuthn step-up flow and execution references
have been deployed and contract-tested. Existing realms require an idempotent Admin API migration;
startup realm import is not an update mechanism.

Password reauthentication is a separate assurance type and never silently becomes hardware
assurance. A password fallback for an administrative mutation is permitted only after a separate,
typed maker-checker workflow exists. Its approval must bind workspace, action, resource, target
version and canonical payload hash; use a distinct human checker; expire quickly; revalidate policy;
and be consumed atomically once. Until that workflow is implemented for an operation, password-only
execution is denied.

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
- Policy-decision context records only normalized assurance and authentication time. Tokens, raw
  claims, WebAuthn assertions and credential identifiers are not audit payloads.
- High-risk actions reject missing, stale or implausibly future authentication times.
- The UI may initiate registration or step-up, but the backend is the final authority and does not
  automatically replay an irreversible request after authentication.
- Production onboarding requires at least two independent human security administrators and tested
  spare-key/revocation recovery before password fallback can be enabled.
