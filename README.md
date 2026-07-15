# DataRiver Next

DataRiver Next is a secure catalog and knowledge-governance control plane around an externally operated DataHub. It preserves catalog search, registration, change management, monitoring and evidence-based Chat, and adds reviewed knowledge-graph changesets/releases, release-pinned API products and grants, Valkey-backed cache/delivery and optional Airflow scheduling.

The runtime is a boundary-enforced modular monolith with independent relay and worker processes. PostgreSQL remains the business source of truth, while modules can later be extracted without sharing domain models or bypassing ports.

## Canonical ownership

| State | Canonical owner |
|---|---|
| Applied catalog metadata | External DataHub |
| Change intent, approval, audit, jobs, ABAC and KG releases | DataRiver PostgreSQL |
| Credentials | External OIDC provider / mounted secret files |
| Uploaded objects | S3-compatible object storage; manifest in PostgreSQL |
| Cache and short-lived delivery | Separate Valkey instances; never canonical |
| Graph query projection | Rebuildable from immutable KG releases |

## Repository map

```text
backend/          FastAPI application, domain modules and workers
frontend/         React + TypeScript web application
infra/            PostgreSQL, Keycloak, Airflow, APISIX and runtime configuration
seed/             explicit deterministic semiconductor seed artifacts
docs/             PRD, architecture, security, API/data specifications and ADRs
scripts/          bootstrap, migration generation and reference-snapshot tools
.github/          portable CI and dependency-update policy
```

The legacy repository is not mixed into this codebase. Its filtered read-only reference snapshot is at `../datariver_v0_3/legacy/datariver_v0_3_reference_20260714`.

## Prerequisites

- Git, Docker Engine/Desktop with Compose v2, at least 8 GiB free memory for core + local identity, and about 12 GiB when Airflow is also enabled.
- An existing DataHub endpoint and a scoped service token. DataRiver does not start, migrate or delete DataHub.
- For local source checks: Python 3.12, `uv 0.9.17`, Node.js 22.19 and npm 10.

No real `.env`, secret, uploaded object, database volume or generated Keycloak realm is committed.

## Git and clean-clone portability

Commit only the repository sources. A second PC clones the same tree, runs the matching bootstrap command below, sets its own DataHub URL/origins, and starts the desired overlays. Do not copy `.env`, `secrets/`, `runtime/`, volumes or uploaded objects through Git. The frozen Python and npm locks plus CI define the reproducible toolchain; production promotes digest-pinned images built from the reviewed commit.

## Local quick start with bundled Keycloak

Linux/macOS/WSL:

```bash
./scripts/bootstrap.sh '<datahub-service-token>'
# Set DATAHUB_BASE_URL in .env to the existing DataHub REST base URL.
docker compose -f compose.yaml -f compose.identity.yaml config --quiet
docker compose -f compose.yaml -f compose.identity.yaml up -d --build --wait
docker compose --profile tools -f compose.yaml -f compose.identity.yaml \
  run --rm local-bootstrap
```

Bootstrap is safe to rerun: it preserves every existing infrastructure credential, updates only the supplied DataHub token, and regenerates derived SeaweedFS/Keycloak configuration from the preserved credentials. Credential rotation is a separate deliberate operation followed by restart and dependency-specific verification.

PowerShell:

```powershell
./scripts/bootstrap.ps1 -DataHubToken '<datahub-service-token>'
# Set DATAHUB_BASE_URL in .env.
docker compose -f compose.yaml -f compose.identity.yaml config --quiet
docker compose -f compose.yaml -f compose.identity.yaml up -d --build --wait
docker compose --profile tools -f compose.yaml -f compose.identity.yaml `
  run --rm local-bootstrap
```

Open `http://localhost:8080`, sign in as `datariver-admin`, and read the generated temporary password from `secrets/keycloak_demo_password`. The first sign-in requires a new password and TOTP enrollment so high-risk approval/publish operations satisfy strong-auth policy. Enter workspace ID:

```text
00000000-0000-4000-8000-000000000100
```

The `local-identity` bootstrap is rejected when `APP_ENV=production`. With an enterprise IdP, provision `(issuer, sub)` and a workspace membership through the controlled environment onboarding process; do not reuse local identities.

## Deployment profiles

```bash
# Core with external OIDC/DataHub
docker compose up -d --build --wait

# Local identity
docker compose -f compose.yaml -f compose.identity.yaml up -d --build --wait

# Scheduled DataHub projection sync and probes (DAGs paused initially)
docker compose -f compose.yaml -f compose.airflow.yaml up -d --build --wait

# Local API gateway on http://localhost:9080
docker compose -f compose.yaml -f compose.gateway.yaml up -d --build --wait

# Entire local integration stack; all overlays compose together
docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
```

Overlays may be combined. Keep PostgreSQL, Valkey, SeaweedFS, DataHub credentials and worker databases on private networks. See [deployment operations](docs/08_DEPLOYMENT.md) before using a non-local environment.

If another local stack owns a default port, host bindings can be overridden for headless integration verification, for example:

```bash
WEB_PORT=18080 KEYCLOAK_PORT=18081 APISIX_PORT=19080 \
  docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
```

An OIDC issuer is an identity, not merely a port mapping. For browser sign-in on alternate ports, also change `APP_PUBLIC_ORIGIN`, `OIDC_PUBLIC_ORIGIN`, `OIDC_PUBLIC_AUTHORITY` and `OIDC_ISSUER` consistently in `.env`, then rebuild web/API/Keycloak. Never accept tokens from two issuer strings for convenience.

## Main functional flows

- Catalog: an authorized local projection is searched first; selected details are enriched through a fixed DataHub adapter. A `sync_id`-bound full reconciliation is sequential, single-writer and tombstones missing DataHub-owned assets without touching seed-owned rows. Airflow obtains short-lived Keycloak service tokens automatically.
- Registration: browser multipart upload goes directly to quarantine storage. Workers complete the object, stream SHA-256/size/format checks with bounded memory, and promote accepted objects. An accepted upload can create an evidence-linked DataHub aspect proposal that still requires normal governance approval.
- Change management: typed DataHub aspect UPSERT requests move through legal transitions and distinct final approval. Confidential/restricted changes need two final approvers. A leased worker applies each aspect idempotently and only marks `APPLIED` after re-read hash equality.
- Knowledge graph: create a graph/ontology, author typed node/edge changesets, validate, independently review, publish or roll back immutable releases, export governed views and call bounded analysis. Raw SQL/Cypher is never accepted.
- API sharing: create a release-pinned contract version, publish it with recent strong authentication, grant an OIDC `client_id` explicit scopes/classification/validity and quotas, revoke it, and invoke bounded neighbor analysis through an atomic grant-and-usage check.
- Chat: deterministic baseline answers only from catalog or active-release knowledge evidence that passed prefiltering and per-item authorization; exchanges and citations are persisted. An external model adapter may be added only after the same evidence boundary.
- Monitoring: liveness, readiness, dependency capabilities, workspace counts, outbox dead letters and ABAC-protected Prometheus HTTP metrics remain independent so one degraded optional dependency does not hide core state.

The bundled Airflow password file and `SimpleAuthManager` are strictly loopback local-development conveniences. Before any non-local Airflow exposure, use the deployment's supported enterprise/FAB SSO integration; the included DAG service account already uses short-lived Keycloak client credentials for DataRiver API calls.

OpenAPI is available at `http://localhost:8000/api/docs` outside production, or through the web proxy at `/api/docs` when enabled.

## Optional semiconductor seed

The seed is deterministic synthetic reference data and never installs by default. It contains 12 catalog assets and a 257-node/279-edge semiconductor value-chain release, including 168 monthly facility-capacity and product-demand observations with assertion-level provenance.

```bash
docker compose --profile semiconductor-seed run --rm semiconductor-seed
docker compose --profile semiconductor-seed run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
docker compose --profile semiconductor-seed run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed remove --confirm-synthetic-data
```

Apply/remove require explicit confirmation. Production mode rejects any non-`none` seed profile.

## Source verification

```bash
uv sync --frozen --all-extras
uv run ruff format --check backend/src backend/tests infra/airflow/dags
uv run ruff check backend/src backend/tests infra/airflow/dags scripts/generate_initial_migration.py scripts/verify_static.py
uv run mypy backend/src backend/tests
uv run pytest backend/tests -q
uv run python scripts/verify_static.py

cd frontend
npm ci
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

CI repeats these checks, audits dependencies, scans source/IaC and release-equivalent backend/frontend images, emits CycloneDX SBOMs, verifies the generated Alembic migration, compiles Airflow DAGs and validates each Compose overlay. The local Compose/OIDC/RLS/gateway/recovery evidence and the remaining production gates are recorded in [the acceptance report](docs/12_ACCEPTANCE_REPORT.md).

## Security invariants

- Application ABAC and PostgreSQL RLS remain mandatory even behind APISIX.
- Search/list/count, Chat evidence, export and analysis use the same workspace/classification boundary.
- Requester final self-approval is forbidden; high-risk operations require recent strong authentication.
- API, relay, upload, governance, bootstrap and migration database identities are separate; each worker receives only its own table grants and mounted secrets.
- DataHub writes cannot bypass governance, and an external acknowledgement alone never means applied.
- Valkey loss affects latency/delivery only; PostgreSQL outbox and leased job state recover correctness.
- Secrets are mounted as files. Production rejects HTTP external endpoints, wildcard CORS and seed activation.
- Web Nginx and APISIX re-resolve replaceable API containers; a rolling API replacement must not require restarting the UI.

Start with the [artifact index](docs/README.md), [PRD](docs/01_PRD.md), [architecture](docs/03_ARCHITECTURE.md), [ABAC model](docs/07_SECURITY_ABAC.md) and [API specification](docs/05_API_SPEC.md).

## License

DataRiver project code is distributed under the [Apache License 2.0](LICENSE). Dependencies and container images remain under their own licenses and must pass the inventory/review gate in [constraints](docs/02_CONSTRAINTS.md).
