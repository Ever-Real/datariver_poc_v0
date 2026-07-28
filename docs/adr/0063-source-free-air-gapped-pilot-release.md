# ADR-0063: Source-free air-gapped amd64 Pilot release

- Status: Accepted
- Date: 2026-07-28
- Owners: Application, Security and Operations

## Context

The preparation PC receives reviewed source through `origin/dev`, but the isolated Linux amd64
Pilot server must not contain a Git checkout or build toolchain. The server may not reach an image
registry or package index. A repeatable Pilot update therefore needs every runtime image and Python,
Node and OS runtime dependency before the release crosses the network boundary.

ADR-0034 requires exact-commit release provenance and a recoverable source artifact. That remains
true, but the source artifact is retained in the authorised development/release archive; it is not
copied to the runtime server.

## Decision

1. `scripts/export_release.sh --commit <full-sha>` runs only from a clean checkout at that exact
   commit on a Linux amd64 Docker host. It builds release-tagged backend, web, Keycloak and
   PostgreSQL-init images, imports the digest-pinned Redis image, records image IDs/platforms, and
   creates one checksummed `release.tar.gz`.
2. The archive contains one `images.tar`, `deploy/pilot/docker-compose.yaml`, environment and secret
   templates, the Keycloak realm template and `scripts/deploy_pilot.sh`. It contains no standalone
   source checkout/bundle, Git metadata, environment values, credentials, database files or Docker
   volumes. The backend image necessarily contains the executable Python application modules and
   Alembic runtime.
3. The Pilot Compose file contains no `build:` and every service uses `pull_policy: never`.
   PostgreSQL, Redis, the DataRiver backend/web and the local Keycloak runtime use only tags loaded
   from the verified archive. API, database and Redis ports are not published; the included
   application endpoints remain loopback upstreams for an approved HTTPS ingress.
4. `scripts/deploy_pilot.sh` verifies archive checksums and linux/amd64 image inventory, loads the
   images, starts infrastructure, runs Alembic `upgrade head` as a one-shot backend container, runs
   the idempotent non-production local-identity bootstrap, and then starts the application.
5. `/home/datariver/.env` contains non-secret deployment values and secret references.
   `/home/datariver/secrets/` contains one owner-readable file per credential. Release export never
   copies either location.
6. The fixed bundled connector scope is PostgreSQL, Redis and Keycloak. DataHub, S3-compatible
   storage, Airflow, LLM, graph and observability services remain independently operated endpoints.
   Their browser/server reachability and distribution approvals are not inferred by the bundle.
7. This is `APP_ENV=development`, `DEPLOYMENT_TIER=SINGLE_NODE_PILOT`. It is not an HA, DR,
   security, capacity or production acceptance claim. Production promotion still uses `main`,
   approved ingress/DNS/TLS, production identity onboarding and the gates in `docs/08_DEPLOYMENT.md`.

## Security and operational consequences

- The target needs Docker Engine and Compose v2, enough disk for the compressed archive and loaded
  images, and an operator-owned backup/restore procedure. Application libraries do not need to be
  installed on the target.
- The release is immutable and commit-bound; configuration and credentials remain mutable host
  state. Updating an image does not update or delete named volumes.
- Initial Keycloak realm import is safe only for a new Keycloak volume. The deployer refuses to
  silently change an already-applied public origin; that change requires an explicit identity
  reconfiguration review.
- Browser use through an IP still requires an organisation-approved TLS certificate/edge for a
  secure context. Direct HTTP on a private IP is not promoted as an authentication profile.
- Redis image redistribution is subject to the exact-image legal decision recorded by the
  operator. MinIO and Neo4j are not included by this Pilot bundle.
- Rollback selects the prior image/Compose release only after checking database compatibility.
  Volumes are never deleted by either release script.

## Rejected alternatives

- Building on the isolated server: requires source, build tools and dependency/index access.
- Letting Compose pull missing images: nondeterministic and unusable in the air gap.
- Packaging real `.env`, secrets or volumes: crosses deployment trust boundaries and risks
  credential/data disclosure.
- A general import/apply/status framework: unnecessary for this Pilot; two auditable shell scripts
  and standard Docker inspection are sufficient.
