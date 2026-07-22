# ADR-0034: Multi-architecture runtime configuration and release bundles

- Status: Accepted
- Date: 2026-07-22
- Refines: ADR-0013, ADR-0028, ADR-0033

## Context

The development host runs Linux containers on Apple Silicon (`linux/aarch64`) while the Windows
WSL preparation host runs Linux containers on x86-64 (`linux/x86_64`). Docker reports host aliases,
but OCI image platforms use `linux/arm64` and `linux/amd64`. A byte-identical image cannot execute
natively on both architectures, and independently rebuilding mutable tags does not prove that the
two artifacts came from the same reviewed source and dependency set.

The web build also previously embedded the development host's OIDC authority and redirect origin
in its JavaScript. Copying an amd64 image cross-built with those values would produce a syntactically
valid image that redirects the WSL browser to the Mac ports. Connection configuration split between
an environment file and development-only database activation would add another ambiguous source of
truth during cutover.

## Decision

DataRiver publishes one logical release with separate `linux/arm64` and `linux/amd64` artifacts.
Parity means the same clean Git commit, Dockerfiles, lockfiles, reviewed base-image indexes and
release inventory; it does not mean the same image ID or tar checksum. Release tooling normalizes
`aarch64` to `arm64` and `x86_64` to `amd64`, refuses an uncommitted source tree, and records the
source commit, platform, tool versions, image IDs/digests and artifact SHA-256 values in an immutable
release index.

Browser-safe OIDC/API settings are injected when the web container starts. They are not image build
arguments. The same architecture-specific web artifact can therefore be promoted between hosts
without inheriting the build host's URLs. Runtime generation validates and escapes the public
values, writes only to the container's temporary filesystem and exposes no credential.

Each deployment selects one ignored environment file and mounted secret directory. Environment
files hold non-secret addresses, feature switches, bucket names and secret *references*; secret
values remain in mounted files. Compose interpolation and container `env_file` must use the same
selected file. Database-backed System Settings remains available for the development workflow
defined by ADR-0028, but these Mac and WSL deployment profiles keep startup activation disabled so
there is one live configuration source.

The base DataRiver release owns PostgreSQL, migrations and application processes. Keycloak is an
optional bootstrap identity overlay when no external OIDC service is provided. Redis, S3/MinIO,
DataHub, graph, Airflow, LLM and observability stay externally operated connectors. For a
single-host pilot, separately composed local connectors join an explicitly named external Docker
network; remote connectors use private DNS/TLS. Published host ports and `host.docker.internal` are
compatibility paths, not the primary container-to-container contract on Linux.

Artifact groups are independent:

- core DataRiver application, PostgreSQL and optional local Keycloak;
- optional operator-owned local connector reference images;
- optional Airflow, APISIX, graph and observability images;
- an exact-commit Git source bundle with its own checksum.

Import verification checks artifact hashes, target platform, loaded image identity, source commit
and a no-build/no-pull Compose rendering before migration. Database and object data use logical
backup/restore and reconciliation; Docker volumes are never copied between architectures. Redis
cache is discarded. Delivery workers are quiesced around a queue cutover so PostgreSQL outbox and
inbox state can recover deterministically.

## Resource and availability boundary

Both named PCs remain **Single-node Pilot** environments. Splitting processes into containers or
repositories preserves service boundaries but does not create HA. An HA claim still requires the
failure-domain, quorum, off-host storage, failover and restore evidence in ADR-0013.

Low-resource profiles keep browser result pages at no more than 100 rows, avoid client-side “all
rows” traversal, and start optional workers/connectors only for enabled capabilities. DataRiver
remains a boundary-enforced modular monolith until measured scaling, availability or ownership
evidence justifies extracting a service.

## Consequences

- Existing steps that export an amd64 image from the Mac are blocked until runtime web
  configuration and release provenance verification pass.
- `.env.dev`-style files are acceptable and preferred here, provided they are ignored, selected
  explicitly and contain no literal credentials. Committed examples describe their schema.
- The System Settings inventory remains useful for visibility and development probes without
  becoming a second production configuration controller.
- Redis and MinIO distributions, tags, licenses and target digests remain an operator acceptance
  decision. DataRiver compatibility does not authorize redistribution.
- Preparation-host installation is repeatable without claiming production or HA readiness.

## Required evidence

1. arm64 and amd64 release indexes name the same clean Git commit and logical image inventory;
2. the web image starts twice with different public OIDC origins without a rebuild and uses the
   selected runtime values in both the main page and silent callback;
3. Compose rendering uses one selected environment file for interpolation and process settings;
4. local connector DNS resolves through the named external network, while remote profiles use
   approved private endpoints and mounted secrets;
5. import verification rejects a wrong platform, modified artifact, missing image or mismatched
   source revision before any migration runs;
6. target backup, restore, Alembic upgrade and object reconciliation evidence is attached before
   traffic cutover.
