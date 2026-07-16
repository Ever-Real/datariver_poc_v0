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
- Production supports the stable DataHub `v1.6.0` contract and enforces the external runtime version;
  the external deployment pins each component using `infra/contracts/datahub-v1.6.0-images.json`.
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

Open `http://localhost:8080`, sign in as `datariver-admin`, and read the generated temporary password from `secrets/keycloak_demo_password`. The first sign-in requires a new password but does not request a mobile OTP. The local realm keeps ordinary login at LoA 1 and reserves its user-verifying cross-platform WebAuthn key for an explicitly requested LoA 2 step-up. High-risk operations remain fail-closed until the user enrolls a key, completes step-up, and the resulting token satisfies the configured ACR, AMR and `auth_time` contract. Enter workspace ID:

```text
00000000-0000-4000-8000-000000000100
```

Use **USB 보안키 등록** in the signed-in profile area to enroll a FIDO2 security key. A denied
high-risk action shows **보안키로 인증** and returns to the same `?page=...` view after Keycloak
step-up. DataRiver never replays the approval or publish request automatically; review it and click
the operation again. The local identity profile has no mobile-OTP setup step.

The `local-identity` bootstrap is rejected when `APP_ENV=production`. With an enterprise IdP, provision `(issuer, sub)` and a workspace membership through the controlled environment onboarding process; do not reuse local identities.

## Host-development quick start

Use this topology while API, workers and UI are changing frequently. PostgreSQL, the two Valkeys, SeaweedFS, Keycloak and APISIX stay in containers; Uvicorn, all four long-running backend relay/workers and Vite run directly from the checked-out source. The production-oriented base Compose remains private by default; `compose.host-dev.yaml` publishes only the required development ports on loopback.

Every repository Compose/host-development combination is a **Single-node Pilot**, even if multiple
processes run on that host. HA requires independent nodes, off-host distributed storage and accepted
failover/restore evidence; replica settings alone are not an HA claim (ADR-0013).

The v1 repository still does not own DataHub. The example below reuses a DataHub GMS already exposed on host port `8080`; replace both URLs and the scoped token when the external service is elsewhere.

For a native Windows checkout, bootstrap from PowerShell. First use includes `-DataHubToken '<scoped-token>'`; later runs preserve the existing token when omitted.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 `
  -HostDevelopment -DataHubBaseUrl http://host.docker.internal:8080
```

For a checkout stored inside WSL, bootstrap and run Docker commands in that WSL distribution so Linux file permissions are preserved:

```bash
./scripts/bootstrap.sh --host-development \
  --datahub-base-url http://host.docker.internal:8080
docker compose -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  config --quiet
docker compose -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  up -d --build --wait postgres valkey-cache valkey-queue seaweedfs keycloak
./scripts/configure_keycloak_host_dev.sh
docker compose -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  run --rm migrate
docker compose -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  run --rm storage-init
docker compose --profile tools -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm local-bootstrap
```

Run the changing source processes from Windows PowerShell so the supported Windows uv/Node toolchains are used:

```powershell
# Create this once with the supported native Windows uv/Python toolchain.
uv venv --python 3.12 .venv
$env:VIRTUAL_ENV = (Resolve-Path .venv).ProviderPath
uv sync --active --frozen --all-extras

powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 `
  start -DataHubBaseUrl http://127.0.0.1:8080
```

When the same checkout is also tested from WSL, keep its interpreter separate so it cannot replace
the native Windows host runtime: `UV_PROJECT_ENVIRONMENT=.venv-wsl uv sync --frozen --all-extras`.

Start the gateway from WSL only after the Windows host API is live. The script discovers the current WSL-to-Windows gateway address:

```bash
./scripts/start_gateway_host_dev.sh
```

Open Vite at `http://localhost:5173`, API docs at `http://localhost:8000/api/docs`, Keycloak at `http://localhost:18081`, and APISIX at `http://localhost:9080`. Vite proxies `/api` through APISIX. Inspect or stop host processes with `./scripts/dev.ps1 status` and `./scripts/dev.ps1 stop`. Runtime PIDs and logs are written only below the ignored `runtime/host-dev/` directory.

The host process manager starts Uvicorn first and requires `/api/v1/health/ready` before starting
workers or Vite. `/health/live` proves only that the process is running; readiness also leases an
API database connection and requires the packaged sole Alembic head. If readiness reports
`SCHEMA_REVISION_MISMATCH`, run the documented migration command before restarting host processes.

The host-development port map is: PostgreSQL `5432`, cache Valkey `6379`, queue Valkey `6380`, SeaweedFS S3 `8333`, Uvicorn `8000`, APISIX `9080`, Keycloak `18081`, and Vite `5173`. Do not run a bare `docker compose up` for this topology because that would also start the containerized API, workers and web service.

Database connection ceilings are explicit settings. Budget the server for
`API replicas × (DATABASE_POOL_SIZE + DATABASE_POOL_MAX_OVERFLOW) + long-running workers ×
(WORKER_DATABASE_POOL_SIZE + WORKER_DATABASE_POOL_MAX_OVERFLOW) + migration/seed/IdP/Airflow/admin
reserve`. The current one-API/four-worker defaults can lease at most 60 DataRiver runtime
connections before that reserve; this is a ceiling calculation, not a recommended production
`max_connections` value.

The repository includes a fail-closed PgBouncer/RLS probe contract and source tests, but the
development or production database path does not deploy PgBouncer. A target transaction-mode
pooler must pass the live two-workspace connection-reuse probe before adoption.

Apply and verify the optional synthetic semiconductor reference data after migration and local identity bootstrap:

```bash
docker compose --profile semiconductor-seed -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm semiconductor-seed
docker compose --profile semiconductor-seed -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
```

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

- Catalog: an authorized local projection serves cursor-bound search, facets and autocomplete before selected details are enriched through a fixed DataHub adapter. A `sync_id`-bound full reconciliation is sequential, single-writer and tombstones missing DataHub-owned assets without touching seed-owned rows. Airflow obtains short-lived Keycloak service tokens automatically.
- Registration: browser multipart upload goes directly to quarantine storage. Workers complete the object, stream SHA-256/size/format checks with bounded memory, and promote accepted objects. An accepted upload can create an evidence-linked DataHub aspect proposal that still requires normal governance approval.
- Change management: typed DataHub aspect UPSERT requests move through legal transitions and distinct final approval. Confidential/restricted changes need two final approvers. A leased worker applies each aspect idempotently and only marks `APPLIED` after re-read hash equality.
- Classification access administration: eligible human security administrators can review and independently approve versioned four-class Search/Chat policies, review or revoke immutable inference-provider profile versions, and govern policy-bound RESTRICTED Search grants. The Admin UI never accepts provider endpoints or credentials, and RESTRICTED evidence is never eligible for Chat.
- Knowledge graph: create a graph/ontology, author typed node/edge changesets, validate, independently review, publish or roll back immutable releases, export governed views and call bounded analysis. Raw SQL/Cypher is never accepted.
- API sharing: create a release-pinned contract version, publish it with recent strong authentication, grant an OIDC `client_id` explicit scopes/classification/validity and quotas, revoke it, and invoke bounded neighbor analysis through an atomic grant-and-usage check.
- Chat: deterministic baseline answers only from catalog or active-release knowledge evidence that passed prefiltering and per-item authorization. Immutable chunks bind workspace, classification, typed scope, source/version/effective time and content hash; only validated cited chunk IDs are persisted, otherwise the answer is `검증 불가`. A disabled-first typed inference worker contract rejects SQL, Cypher, arbitrary HTTP, tools and mutation fields and validates cited output, but no provider adapter, endpoint, secret, durable job or external call is wired. External inference remains disabled until live revalidation, delivery/streaming, metrics and scaled red-team gates are accepted.
- Monitoring: liveness, readiness, dependency capabilities, workspace counts, outbox dead letters and ABAC-protected Prometheus HTTP metrics remain independent so one degraded optional dependency does not hide core state. Database-pool metrics expose only bounded connection states and configured limits, never workspace, subject or query labels.

SeaweedFS is the local/Pilot upload store, not accepted WORM storage. The immutable-archive port is
promoted only against a maintained, target-specific S3 deployment that passes Object Lock negative
conformance and restore gates. Archived MinIO OSS is not the default for new production deployments;
see ADR-0012 for the governed legacy exception and provider-neutral alternative.

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
uv run ruff check backend/src backend/tests infra/airflow/dags scripts/configure_keycloak_assurance.py scripts/generate_initial_migration.py scripts/probe_pgbouncer_rls.py scripts/probe_policy_revocation.py scripts/verify_datahub_contract.py scripts/verify_static.py
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

Before production promotion, verify the external DataHub runtime independently of application
startup:

```bash
uv run python scripts/verify_datahub_contract.py --base-url https://datahub.example.internal
```

An existing Keycloak realm is not updated by startup import. Apply and re-read the assurance
contract with a file-mounted admin credential. The migration removes a stale mobile-TOTP user
action, adds the AMR mapper, creates and validates the password/LoA-1 plus WebAuthn/LoA-2 flow, and
binds it only after structural verification:

```bash
uv run python scripts/configure_keycloak_assurance.py \
  --base-url https://identity.example.internal \
  --admin-username '<bootstrap-admin>' \
  --admin-password-file /run/secrets/keycloak_admin_password \
  --username '<managed-security-admin>' \
  --configure-step-up \
  --revoke-user-sessions \
  --apply
```

Rerun the same command without `--apply` to perform a read-only drift check. WebAuthn enrollment is
explicit (`webauthn-register:skip_if_exists`) rather than a realm-wide first-login action. The
portable profile accepts user-verifying cross-platform authenticators; production-approved
attestation roots and AAGUID allowlists remain deployment inputs and promotion gates.

The administrator API uses recent hardware WebAuthn for direct membership-access changes. A typed
password-reauthentication Maker-Checker path exists only for the exact
`WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1` command and is disabled by default. Do not enable
`ADMIN_PASSWORD_FALLBACK_ENABLED` until two real eligible human security administrators have been
provisioned and the target IdP/browser `max_age=0` reauthentication plus one-time consume journey
has passed. The local bootstrap does not create a fake second administrator; with the default local
bootstrap the fallback therefore remains unavailable.

For a non-production integration check, add `--probe-browser-flow` and a valid
`--probe-redirect-uri`. The probe creates a random temporary user, proves that LoA 1 issues an
authorization code and access token with `acr=1`, `amr=pwd` and `auth_time`, while LoA 2 stops at
WebAuthn, and removes the user in a `finally` cleanup. It never prints the generated password and
does not attempt to emulate a real security key.

With the local semiconductor seed, Keycloak and host API running, measure same-token policy
revocation against the direct API (100 iterations each for inactive membership, explicit action deny
and system/domain scope removal):

```powershell
uv run python scripts/probe_policy_revocation.py
# Only if a prior process was forcibly interrupted and left its ignored recovery snapshot:
uv run python scripts/probe_policy_revocation.py --recover
```

The probe restores and verifies the original Airflow service membership on every normal/error exit.
It writes only aggregate timings to `runtime/policy-probe/last-result.json`; bearer tokens and raw
membership attributes are never written to the result.

CI repeats these checks, audits dependencies, scans source/IaC and release-equivalent backend/frontend images, emits CycloneDX SBOMs, verifies the generated Alembic migration, compiles Airflow DAGs and validates each Compose overlay. The local Compose/OIDC/RLS/gateway/recovery evidence and the remaining production gates are recorded in [the acceptance report](docs/12_ACCEPTANCE_REPORT.md).

## Security invariants

- Application ABAC and PostgreSQL RLS remain mandatory even behind APISIX.
- Search/list/count, Chat evidence, export and analysis use the same workspace/classification boundary.
- Requester final self-approval is forbidden; high-risk operations require recent strong authentication.
- Administrator self-access changes are forbidden. Password fallback is typed, five-minute,
  Maker-Checker, one-time and default-disabled; it never converts password/OTP into hardware assurance.
- API, relay, upload, governance, bootstrap and migration database identities are separate; each worker receives only its own table grants and mounted secrets.
- DataHub writes cannot bypass governance, and an external acknowledgement alone never means applied.
- Valkey loss affects latency/delivery only; PostgreSQL outbox and leased job state recover correctness.
- Secrets are mounted as files. Production rejects HTTP external endpoints, wildcard CORS and seed activation.
- Web Nginx and APISIX re-resolve replaceable API containers; a rolling API replacement must not require restarting the UI.

Start with the [artifact index](docs/README.md), [PRD](docs/01_PRD.md), [architecture](docs/03_ARCHITECTURE.md), [ABAC model](docs/07_SECURITY_ABAC.md) and [API specification](docs/05_API_SPEC.md).

## License

DataRiver project code is distributed under the [Apache License 2.0](LICENSE). Dependencies and container images remain under their own licenses and must pass the inventory/review gate in [constraints](docs/02_CONSTRAINTS.md).
