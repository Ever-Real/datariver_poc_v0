# ADR-0052: Deployment-aware source-host infrastructure workflow

- Status: Accepted
- Date: 2026-07-27
- Refines: ADR-0034, ADR-0048, ADR-0051

## Context

The same reviewed PostgreSQL image has two local reference forms. A connected build deployment can
resolve the pinned registry reference
`postgres:17.10-bookworm@sha256:<accepted-index>`. A verified offline release uses `docker save`
and `docker load`; Docker restores the accepted image ID and tag but does not reliably restore the
registry digest association. Its release therefore contains a checksum-protected Compose override
that selects `postgres:17.10-bookworm` only after the image ID and target platform have been
verified against the release manifest.

The first WSL source-host procedure exposed that transport detail to the operator. Recreating
PostgreSQL with the base, identity and source-host files but omitting the offline override made
Compose look for the registry-only digest even though the correct tag/image ID was already loaded.
Asking an operator to rediscover `RELEASE_DIR`, order four Compose files and compare image IDs for
each source restart is error-prone and makes build/offline operation appear to use different
software.

## Decision

Add one managed `workflow_source_host_infra.py` action. It reads the selected profile's
permission-restricted applied state and resolves the infrastructure plan:

- build mode uses the digest-pinned base Compose files and the normal build path;
- offline mode resolves the recorded immutable release directory, verifies the checksum sidecars
  for the offline override and core manifest, verifies the loaded PostgreSQL and Keycloak image IDs
  and `linux/amd64` platform, then appends the offline override after the base files;
- both modes append `compose.source-host.yaml`, stop source processes and containerized application
  writers, preserve infrastructure volumes, and start only PostgreSQL and Keycloak;
- both modes display the final Compose services and loopback port publications.

An optional environment argument may select the derived intranet source-host environment, but it
does not select a release or image. Release authority remains the applied state. A missing state,
checksum drift, absent tag, image-ID mismatch, wrong platform or rendered registry-only digest in
offline mode fails before any container is stopped.

The source continues to pin external image indexes. The workflow does not replace them with a
mutable global default, pull an unpinned tag, encode a developer-machine image ID, or claim that
arm64 and amd64 image IDs are identical.

## Consequences

- Preparation-PC operation becomes one command:
  `./scripts/workflow_source_host_infra.py prepare`.
- Operators no longer pass `RELEASE_DIR` or an offline Compose override during routine source
  validation.
- Build and offline modes use the same logical service contract while retaining their necessary,
  independently verified local reference semantics.
- Existing raw Compose commands remain lower-level diagnostics and release/restore tools; they are
  not the normal source-host transition.
- Target WSL Docker execution, actual port observation and browser/provider checks remain external
  gates.
