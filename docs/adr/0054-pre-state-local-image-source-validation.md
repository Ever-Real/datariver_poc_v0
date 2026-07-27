# ADR-0054: Pre-state local-image source validation

- Status: Accepted
- Date: 2026-07-27
- Supersedes: the connected pre-state exception in ADR-0052
- Refines: ADR-0034, ADR-0051, ADR-0052, ADR-0053

## Context

A preparation PC may already have the reviewed PostgreSQL, Keycloak and optional Neo4j AMD64
images but no `runtime/operator-workflow/wsl-preparation.json`. Requiring an additional
`--connected-build` flag made the normal explicit-environment command fail before it could inspect
those local inputs. The old exception also allowed PostgreSQL `pull_policy: missing`, which made a
pre-state source transition depend on registry reachability and was unsuitable for a closed
network.

OIDC is not an optional presentation component in DataRiver. Verified issuer/subject identity
anchors Workspace membership, ABAC decisions, RLS context, audit evidence and Admin assurance.
Removing OIDC for development would create a second authentication architecture and weaken
negative authorization tests.

## Decision

- When managed applied state is absent and the operator supplies an explicit `--env-file`,
  `workflow_source_host_infra.py` automatically selects local-image source validation.
- The workflow renders the reviewed local-reference overlay, verifies both PostgreSQL and Keycloak
  images exist as `linux/amd64`, and then starts them with `--pull never --no-build`.
- Missing or wrong-platform images fail before source processes or container writers are stopped.
- `--reuse-local-images` explicitly forces this path when applied state exists.
  `--connected-build` remains a deprecated compatibility alias and no longer permits a pull.
- The local-image path never writes or claims managed offline release acceptance. Managed state,
  manifest, checksum and image-ID verification remain mandatory for offline acceptance.
- OIDC remains enabled. Preparation-PC-only browser development uses loopback Keycloak through
  `bootstrap.sh --host-development`, which needs no DNS, certificate, Nginx or Windows inbound
  rule. The two-name HTTPS ingress remains optional and is used only for shared intranet browser
  testing.

## Consequences

- The command that failed on a missing state now works unchanged when its explicit environment and
  required local AMD64 images are present.
- Closed-network preparation no longer attempts PostgreSQL or Keycloak registry access.
- Local browser development is separated from shared intranet publication, removing DNS/TLS work
  from the initial source-validation loop without creating an authentication bypass.
- A local tag is development execution input, not release evidence; production and offline
  promotion gates are unchanged.
