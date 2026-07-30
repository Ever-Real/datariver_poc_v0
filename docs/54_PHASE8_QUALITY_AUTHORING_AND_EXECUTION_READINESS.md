# Phase 8 Quality authoring and execution-readiness record

- Date: 2026-07-30
- Scope: V2 authoring directory, bounded Rule proposal, review/activation, manual Run request,
  accessible Quality status visuals
- Decision: [ADR-0079](adr/0079-quality-authoring-readiness-and-manual-run-commands.md)

## Implemented boundary

The server now derives field identities and types from a deployment-owned V2 manifest, then
reconciles them with the current authorization-pruned Catalog asset before accepting a Rule. A
multi-asset proposal is one atomic command bounded to 25 unique targets. Review and activation use
the existing maker-checker and WebAuthn controls; manual execution creates Run, event and outbox
evidence in one database function. The API never accepts source coordinates, GX classes,
connection data, retention values or authorization evidence from the browser.

Capability is intentionally split:

- authoring/activation require a V2 directory and active V3/V4 Quality retention classes;
- manual execution additionally requires the isolated worker to be enabled;
- scheduling remains unavailable without an approved schedule profile.

The Overview provides server-derived result counts and coverage as accessible visuals with
equivalent tables. A null percentage does not render a false progress bar.

## Executed verification and open target gates

The local source gate passed repository Ruff, strict mypy over `481` source/test files,
`1,882` backend tests with `104` explicitly environment-gated skips, static architecture/security
verification, frontend TypeScript/ESLint, `65` frontend files with `356` tests, and the production
build. Two consecutive canonical `0001` generations were byte-identical at SHA-256
`59502d46caa5bd9bb5b6f2764c1e160740586c6724d8d8e69bc0887bd5d83033`.

An isolated PostgreSQL `17.10` database accepted the regenerated canonical `0001` and the actual
`0070 -> 0071` authoring-command upgrade. Five live tests passed: current-head semantic
fingerprint and rollback after function/RLS/grant/constraint/trigger drift, current-target drift
denial, complete V3 retention genesis, concurrent Legal Hold generation, and the `0071` manual
Run command. The last test proved one transaction creates the canonical `QUEUED` Run, matching
initial Run event and `quality.validation_run.queued.v1` outbox row. This is a local isolated
database claim, not target-source or production acceptance.

The local deployment has no approved V3/V4 Quality retention values, V2 target manifest,
read-only TLS source principal, fixed egress identity or enabled Quality worker. Those values are
owned by operations/security and are not fabricated in source. Consequently a real semiconductor
full-table GX Run and DataHub service-principal collection remain external target gates, while
local capabilities stay fail-closed.

## Deferred medium/low items

- make authoring readiness distinguish a complete V3/V4 policy class set from a policy containing
  only the three Quality classes; the mutation function already rejects the incomplete set;
- enforce workload-profile `max_concurrency` across worker replicas;
- assert manifest lease duration equals the deployed worker lease;
- hydrate V4 policy details in the retention administration repository;
- reconcile the stale semiconductor bootstrap manifest `postgres.applied` observation;
- add scheduled authoring only after an approved schedule-profile directory exists.
