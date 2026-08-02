# ADR-0111: Source-built AMD64 portability readiness layer

- Status: Accepted for P0-A
- Date: 2026-08-03
- Owners: DataRiver application, security and operations owners

## Context

The arm64 development PC publishes committed source to `origin/dev`; the Linux/WSL amd64
preparation PC fast-forwards that exact source and builds or runs it locally. Application images,
containers and registries are not a delivery mechanism between those PCs. The stable operator
interfaces are `development_cycle.py dev-publish`, `prep-update` and `prep-check`.

Previously, successful migration and health output was visible during a run but there was no
machine-readable binding between the last successful preparation runtime, its exact source,
toolchain, lockfiles and host-local configuration shape. A later failed update could therefore be
confused with the last runtime that had actually passed all gates.

## Decision

P0-A adds an ignored host-local readiness manifest at
`runtime/portability/amd64-readiness.json` with contract identity
`DATARIVER_PREPARATION_READINESS_V1`. It is evidence for the **last fully successful** preparation
run, not an assertion that an arbitrary current checkout is running.

`prep-update` retains its existing branch, origin, fetch, fast-forward, dependency-sync,
source-host bootstrap, migration, start and health semantics. Before updating, it validates any
existing manifest and requires its successful source SHA to be an ancestor of the current `dev`
checkout. After the update, it records a new manifest only when all of the following have passed:

1. host and Docker server are Linux amd64;
2. `HEAD` and the live-verified `origin/dev` SHA are identical;
3. the Python and frontend lock hashes and pinned toolchain versions are readable;
4. canonical and selected environment **key-name** schemas are hashed without values;
5. the bounded, non-secret selected topology and existing preflight capabilities are captured;
6. the packaged database revision equals the sole Alembic head; and
7. API readiness, Web and loopback OIDC health probes succeed.

The API readiness endpoint already accepts only the packaged database revision. Therefore a
successful API readiness probe, combined with the packaged-revision/sole-head comparison, is the
P0-A proof that Alembic current equals head. No second database credential path is introduced.

The manifest is written through a same-directory temporary file, `fsync`, mode `0600` and atomic
replacement. A failed migration, process start, capability check, health probe, evidence build or
atomic replacement leaves the previous successful manifest unchanged. `prep-check` is read-only:
it gathers the same evidence and requires an exact match, excluding only `recorded_at`.

The manifest contains no environment values, value hashes, secret references, credentials or
model identifiers. Preflight output is projected onto an explicit allowlist before persistence or
operator logging; parse failures report only a bounded validation message and never echo raw JSON.

## Compatibility

- Command names, choices, default environment file and required arguments do not change.
- `prep-update` remains the only daily command that fetches and fast-forwards `origin/dev`.
- `prep-check` does not fetch; it verifies the current checkout, local `origin/dev`, runtime and
  last successful manifest.
- `.env.wsl-intranet-development`, `secrets/` and the manifest remain host-local and ignored.
- No Docker image export/import, registry, new daily command, branch or worktree is introduced.

## Deferred decisions

P0-B owns target-native offline dependency-cache matching and any build failure proven on an
actual amd64 host. P0-C owns canonical local/external/disabled connector selection, selective
health gates, pre-migration backup evidence and restore operations. This ADR does not authorize a
Dockerfile, Compose topology, environment-schema or backup change.

## Evidence boundary

Mac source-only tests can prove parsing, hashing, secret exclusion, atomic failure behavior and
stable command structure. Actual Linux amd64/WSL execution, Docker daemon identity, migration,
runtime health and operational recovery remain target-environment gates until run there.
