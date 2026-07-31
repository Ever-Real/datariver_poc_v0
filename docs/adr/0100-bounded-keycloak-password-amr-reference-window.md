# ADR-0100: Bounded Keycloak password AMR reference window

- Status: Accepted
- Date: 2026-07-31
- Owners: Security/Identity, Governance, Application
- Refines: ADR-0009, ADR-0025, ADR-0087

## Context

DataRiver verifies password reauthentication from the combined OIDC `acr`, `amr` and
`auth_time` claims. Keycloak emits an authentication-method reference only while the authenticator
execution time plus `default.reference.maxAge` is not earlier than the current time.

The managed password execution configured `default.reference.maxAge=0`. An authorization-code
exchange normally completes after the password execution second, so otherwise valid fresh login
tokens intermittently omitted `amr=pwd`. The API then correctly classified the token as `UNKNOWN`
and denied Governance Document publication. Repeating login refreshed `auth_time` but did not make
the absent password-method evidence trustworthy.

## Decision

The managed `datariver-password-reference-v1` execution retains its `pwd` AMR reference for 300
seconds. This equals the default high-risk authentication age and remains within the application's
existing bounded configuration.

This reference window is not an authorization TTL. The API continues to require:

- the configured password ACR;
- `amr=pwd`;
- a valid `auth_time`;
- the deployment's `HIGH_RISK_AUTH_MAX_AGE_SECONDS` check;
- every existing action, actor, maker-checker, Workspace, RLS and lifecycle constraint.

The Keycloak assurance migration upgrades only the exact legacy `pwd` configuration with
`default.reference.maxAge=0`. Any other alias, reference value or configuration drift fails closed
instead of being overwritten. The WebAuthn execution and its reference age are unchanged.

## Consequences

- A fresh password reauthentication token consistently carries the evidence required by the
  development-only Governance Document password exception.
- Tokens older than the API's configured maximum authentication age remain denied even if they
  still contain `amr=pwd`.
- Existing realms require the assurance configuration script to apply the exact legacy upgrade;
  new realms receive the corrected value from the canonical realm template.
- Production hardware-WebAuthn requirements and unrelated high-risk actions are unchanged.
