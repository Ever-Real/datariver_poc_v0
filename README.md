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

## Prerequisites

- Git, Docker Engine/Desktop with Compose v2, at least 8 GiB free memory for core + local identity, and about 12 GiB when Airflow is also enabled.
- Production and shared environments require an externally operated DataHub endpoint and scoped service token. The supported Mac development topology below starts an isolated local DataHub v1.6.0 instead.
- `DATAHUB_EXPECTED_VERSION` is a required deployment setting and must be an exact stable release;
  the current example is `v1.6.0`. The external deployment pins each component using its reviewed
  contract (the current example is `infra/contracts/datahub-v1.6.0-images.json`) and proves its
  rendered images with `scripts/verify_datahub_image_inventory.py`.
- For local source checks: Python 3.12, `uv 0.9.17`, Node.js 22.19 and npm 10.

No real `.env`, secret, uploaded object, database volume or generated Keycloak realm is committed.

## Git and clean-clone portability

Commit only the repository sources. A second PC clones the same tree, runs the matching bootstrap command below, sets its own DataHub URL/origins, and starts the desired overlays. Do not copy `.env`, `secrets/`, `runtime/`, volumes or uploaded objects through Git. The frozen Python and npm locks plus CI define the reproducible toolchain; production promotes digest-pinned images built from the reviewed commit.

## Validated Mac development PC

This is a single-developer topology, not a production deployment. On a 32 GiB Mac, set Docker Desktop to **16 GiB memory and 6 CPUs** by default, or at most **18 GiB** for a bounded large import; Ollama runs natively on macOS outside that limit. The selected `datariver-gemma4-dev:0.1` model reuses Gemma4 E2B QAT weights with an 8,192-token context ceiling. Do not run a second Ollama container.

The first bootstrap generates a private local DataHub placeholder token, all DataRiver/Neo4j secrets and the Keycloak realm. It does not copy another machine's `.env`, volumes or credentials. The separate DataHub wrapper obtains the official `v1.6.0` source checkout under ignored `runtime/` and starts its official Apple-Silicon `without-neo4j` topology. `without-neo4j` is intentional: DataHub lineage remains in DataHub; the separate Neo4j service below is a rebuildable **DataRiver knowledge-graph projection sandbox**, never a DataHub database.

```bash
# Native macOS Ollama must already be running. This reuses the Gemma4 E2B QAT
# weights and creates a local 8,192-token development derivative.
./scripts/prepare_ollama_mac_dev.sh

./scripts/bootstrap.sh --mac-development
./scripts/start_datahub_mac_dev.sh start

docker compose --profile observability \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml config --quiet
docker compose --profile observability \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  up -d --build --wait
docker compose --profile tools -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml -f aux-compose.yml \
  -f compose.graph.yaml run --rm local-bootstrap

# Optional but recommended: deterministic catalog/KG test data.
docker compose --profile semiconductor-seed -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml -f aux-compose.yml \
  -f compose.graph.yaml run --rm semiconductor-seed
docker compose --profile semiconductor-seed -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml -f aux-compose.yml \
  -f compose.graph.yaml run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
```

Use DataRiver at `http://localhost:18080`, its gateway at `http://localhost:19080`, local DataHub GMS at `http://localhost:8080`, DataHub UI at `http://localhost:19002`, Neo4j Browser at `http://localhost:17474`, and Neo4j Bolt at `bolt://localhost:17687`. The local model is reached only by backend containers through `host.docker.internal:11434`; it receives fixed, non-executable typed extraction/citation contracts and cannot execute SQL, Cypher, HTTP requests, files, or DataRiver mutations. The Neo4j volume may be deleted and rebuilt, but PostgreSQL knowledge releases remain canonical. See [ADR-0023](docs/adr/0023-mac-development-local-inference-and-graph-projection.md) for the canonical ownership and development-only security boundary.

On the 32 GiB Mac development host, keep Docker Desktop at `16 GiB` by default and use `18 GiB` only
for bounded large imports rather than raising it to `24 GiB`: the full DataRiver + DataHub stack
uses substantial memory, while the host Ollama
`gemma4` derivative needs separate unified-memory headroom when loaded. Recheck `docker stats` and
`ollama ps` during GraphRAG tests; sustained swap or memory pressure means stop optional services,
not enlarge both Docker and model budgets past physical memory.

## Initialization and verification checklist

Use this sequence for a new environment or a restored database. It is safe to repeat the
non-destructive bootstrap, migration, seed verification and health checks; do not reuse another
environment's secrets or volumes.

1. Read [architecture](docs/03_ARCHITECTURE.md), [deployment](docs/08_DEPLOYMENT.md) and the
   canonical ownership table above. PostgreSQL owns DataRiver workflow state; DataHub is the
   external owner of applied catalog metadata; S3-compatible storage owns object bytes; Valkey is
   disposable cache/delivery state.
2. Bootstrap `.env` and ignored secret files with `scripts/bootstrap.sh` or
   `scripts/bootstrap.ps1`. Set the external DataHub base URL, service token, OIDC origins and any
   optional UI links before starting services. `DATAHUB_EXPECTED_VERSION` remains a stable release
   contract. The bundled Mac launcher checks out the exact stable `v1.6.0` commit and uses the
   digest-pinned `v1.6.0` component images; do not add an RC compatibility exception for this local
   topology.
3. Validate the selected Compose overlay with `docker compose ... config --quiet`, then bring up
   PostgreSQL, Valkey, object storage, Keycloak and APISIX. Apply `alembic upgrade head` through the
   migration service before API/workers; readiness requires revision `0038`.
4. Start the API, relay, workers and web service using either the container profile or the
   host-development commands below. Check `/api/v1/health/live`, `/api/v1/health/ready`,
   `/api/v1/capabilities` and the APISIX/Vite proxy before using application workflows.
5. Apply the optional deterministic seed only when synthetic reference data is wanted, then run its
   `verify` command. Never seed production data.
6. Sign in, choose a workspace and complete a catalog, registration and change-request state flow.
   Development can validate normal CR state transitions with the local ordinary OIDC account;
   hardware-key enforcement remains a production-sensitive-operation gate.

### Administrator system configuration

The profile menu presents grouped, server-authorized administration entries. **Accounts & access**
contains Users, Systems, server-managed Role definitions/assignment and the applicable
security/exception workflows;
**Retention & erasure governance** contains policy, Legal Hold and erasure review. Provider
eligibility remains a nested policy approval because it is distinct from connection configuration.

In development, an eligible administrator can open **Profile → System settings** and select a
badge for DataHub, Airflow, S3, the grouped Chat/Embedding/Reranker LLM models, Neo4j, Prometheus or
Grafana. Unconfigured entries start from a
server-owned sample YAML containing no credential values. Each SAVE creates a versioned YAML
revision in PostgreSQL. The browser may save addresses, model identifiers, non-sensitive options
and strict `file:/run/secrets/<name>` references; a literal `password`, `secret`, `token`, `api_key`
or `private_key` value is rejected. Actual values remain in ignored local secret files/Docker
secrets, and `.env` contains only deployment switches or reference paths. Use
`url`, `endpoint` or `base_url` for an HTTP(S)
endpoint. A saved Grafana URL is supplied by the server to the Monitoring page and rendered in its
sandboxed iframe. Production keeps configuration in deployment/approved-provider controls and does
not expose this write API.

**SAVE** validates and versions the YAML. **TEST** runs one fixed server-side probe against that
exact saved revision and never accepts a request URL. **ACTIVATE** is available only for a current
AVAILABLE revision, an implemented runtime consumer and a recent hardware-WebAuthn administrator.
It selects the version for the next process startup; it never hot-reloads or restarts a client.
DataHub GMS and S3 changes require API plus relevant worker restart, while local Ollama Chat and
external UI-link changes require API restart. Embedding, reranker and Neo4j remain honest
storable/testable inventory until their typed runtime adapters exist; their ACTIVATE control stays
disabled. The API can report only the version it loaded itself and does not infer worker success.

For the Mac development topology, bootstrap enables the startup resolver for Workspace
`00000000-0000-4000-8000-000000000100`. After ACTIVATE, recreate the API and relevant workers:

```bash
docker compose -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  up -d --force-recreate api governance-apply-worker upload-worker upload-validation-worker
```

APISIX uses DNS discovery through Docker's embedded resolver, so replacing the API container does
not require restarting the gateway or leave it pinned to the old container address.

The exact state and security boundary are controlled by [ADR-0028](docs/adr/0028-development-system-configuration-startup-activation.md).

### Membership renewal and CR responsibility routing

Human Workspace memberships expire after six calendar months; service accounts remain
operator-managed. A user can request the next six-month term during the final 30 days. Every
eligible global Admin sees the same pending queue, but the requester cannot approve their own
extension and approval requires the existing recent WebAuthn assurance. Existing overdue users get
a 30-day migration transition window. Operate at least two eligible global Admin accounts before a
renewal window opens; browser time is never used as access authority.

Every new CR target now binds to a canonical System. REVIEW and TEST each require Developer
approval evidence for every target System before the next stage. FINAL requires Developer and Data
Steward approval for every target System plus one role-separated global Admin approval. A person
assigned the same responsibility to several Systems may cover those Systems, but one actor cannot
satisfy two FINAL role classes. See [ADR-0026](docs/adr/0026-expiring-human-membership-renewal.md)
and [ADR-0027](docs/adr/0027-change-request-system-role-authority.md).

#### CR workflow and FINAL security boundary

The canonical CR path is `REGISTERED -> IN_REVIEW -> TESTING -> FINAL_REVIEW`. A multi-target,
non-executable `CHANGE_INTAKE` completes after FINAL approval; a single governed DataHub aspect
moves through `APPLY_QUEUED -> APPLYING -> APPLIED|APPLY_FAILED`. A resubmission creates a new
current revision, so an approval or test result from an older revision can never satisfy the new
round. Every state command is version-fenced and idempotent. TEST evidence is a typed run bound to
private attachment bytes and their content hash; the platform does not accept browser-supplied raw
SQL as proof.

Both FINAL approval and FINAL rejection use the typed FINAL decision API. An ordinary transition
cannot bypass that boundary. FINAL approval requires all target Systems' Developer and Data
Steward lanes plus one global Admin lane, with a different actor for each responsibility class.
These sensitive writes additionally require a recent hardware-WebAuthn/LoA-2 session whose
`acr`, `amr` and `auth_time` satisfy the server policy. Password/direct-grant tokens and service
tokens fail closed with `401` or `403`; there is no password downgrade. Immutable policy-decision
evidence remains in `authz.policy_decisions`.

The workflow, negative cases and executed local evidence are recorded in
[the use-case catalogue](docs/usecases.md), [the test checklist](docs/test_checklist.md) and
[ADR-0027](docs/adr/0027-change-request-system-role-authority.md). A successful password-token
denial proves the security gate, not a successful human FINAL approval; production promotion still
requires a real browser and approved hardware authenticator journey.

The administrator navigation contains one **Audit/Log 조회** entry with Metadata Change Log and
System Security Log tabs. Their read/export controls remain unavailable until a workspace-scoped,
masked audit API exists; the UI does not manufacture log rows. Retention policy, Legal Hold and
erasure review are three stages in one lifecycle: default duration, exceptional hold precedence,
and independent deletion-intent review. Approval still does not execute deletion, and the workflow
is provider-neutral even though PostgreSQL stores its canonical policy/evidence.

WebAuthn enrollment is labelled without a USB assumption. It is the accepted recent-hardware gate
for high-risk direct mutations, not a removable cosmetic menu item. An intranet operator may set
`OIDC_HARDWARE_WEBAUTHN_ENABLED=false`; DataRiver then hides enrollment/step-up and refuses hardware
assurance, so protected mutations stay unavailable rather than falling back to an ordinary password.
Replacing that lost functionality still requires a reviewed assurance alternative that preserves
self-change denial and the two-human administrator invariant.

### Enterprise UI completion scope

The Change Management, Knowledge Management, My Profile and administrator surfaces are controlled
by [the enterprise UI PRD](docs/20_ENTERPRISE_UI_COMPLETION_PRD.md) and its
[completion checklist](docs/21_ENTERPRISE_UI_COMPLETION_CHECKLIST.md). The implementation uses the
current React application, TanStack tables, Tailwind CSS and React Flow; `datariver_v0` is a
read-only interaction reference and is never imported into the v1 runtime.

- Change requests use the existing typed intake, private attachment, approval and transition APIs.
  Their detail dialog has a four-stage Stepper and loads only authorized catalog lineage. Existing
  request-item edits and generated SQL result presentation remain disabled until version-fenced
  server contracts exist. System selection and Developer/Data Steward/global Admin approval lanes
  come from canonical server routing and immutable authority snapshots, never UI fixtures.
- Knowledge Registry and releases use the canonical graph APIs. The visual ontology editor and its
  local `CREATE (alias:Label)`/relationship subset produce typed provenance-bearing changeset
  operations; arbitrary Cypher is rejected and no Cypher string is sent to the server. Integrity-
  verified PDF uploads can enter the governed typed extraction flow; model-selected evidence IDs
  resolve to server-owned page excerpts before a DRAFT changeset is created. DB-schema source
  extraction remains unavailable until its governed proposal/job contract exists.
- Knowledge Chat is a distinct route from general Chat and calls only release-pinned, bounded
  Neo4j evidence retrieval and the graph-specific OpenAI-compatible synthesis contract. An answer
  is accepted only when every cited ID belongs to the authorized evidence bundle and the exact
  model/configuration/prompt/tool versions are audited.
- Profile administrator entries are rendered only from the `/admin/me` operation context. Missing
  audit/security-log exports, IdP user creation, system CRUD and dictionary mutation are shown as
  unavailable instead of using browser mocks or direct provider writes.

This is a development UI, but the same authorization and canonical-ownership boundaries apply.
An empty graph canvas contains a labelled placeholder node so the layout never collapses; it is not
mock domain evidence.

## Local quick start with bundled Keycloak

Linux/macOS/WSL:

```bash
./scripts/bootstrap.sh '<datahub-service-token>'
# Set DATAHUB_BASE_URL in .env to the existing DataHub REST base URL.
# With the host-development Compose profile, backend containers instead use
# DATAHUB_CONTAINER_BASE_URL (default: http://datahub-gms:8080) through the
# external DATAHUB_DOCKER_NETWORK (default: datahub_network).
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

The catalog renders the bounded, authorization-pruned lineage graph itself. Selecting a graph node
opens the authorized local catalog detail. The external DataHub Lineage iframe is intentionally not
invoked by the UI, so DataRiver never depends on a browser DataHub session or forwards a provider
credential. The export worker is an opt-in Compose profile with its own database and S3 credentials.

```powershell
./scripts/bootstrap.ps1 -DataHubToken '<datahub-service-token>' `
  -DataHubEmbedOrigin 'http://127.0.0.1:9002' -EnableCatalogExportWorker
docker compose --profile catalog-export -f compose.yaml -f compose.identity.yaml `
  up -d --build catalog-export-worker
```

Open `http://localhost:8080`, sign in as `datariver-admin`, and read the generated temporary password from `secrets/keycloak_demo_password`. The first sign-in requires a new password but does not request a mobile OTP. The local realm keeps ordinary login at LoA 1 and reserves its user-verifying cross-platform WebAuthn key for an explicitly requested LoA 2 step-up. High-risk operations remain fail-closed until the user enrolls a key, completes step-up, and the resulting token satisfies the configured ACR, AMR and `auth_time` contract. Bootstrap assigns this active default Workspace, so a verified user does not need to type it after login:

```text
00000000-0000-4000-8000-000000000100
```

Workspace is not an Admin-only screen option: it is the tenant/security scope for every user,
membership, RLS, ABAC and cache entry. With `WORKSPACE_SELECTION_ENABLED=true`, the selector is a
validated URL convenience, not browser-stored authority, and every API request rechecks membership.
Set it to `false` for a single-Workspace UI; the selector disappears and DataRiver always uses the
server-verified default while preserving the same internal security boundary. A missing default
fails closed. OIDC user/profile/role state remains in React memory only: startup uses
the Keycloak SSO session for a silent authorization-code + PKCE round-trip, then hydrates the
verified profile from `GET /auth/me`. The local administrator is a `security-administrators` member
and can read its server-derived administrator menu without reauthentication. Password reauth or
hardware WebAuthn is requested only by the corresponding sensitive mutation; no operation is
automatically replayed after that redirect.

Use **WebAuthn 보안키 등록** in the signed-in profile area to enroll an authenticator allowed by the
organization IdP policy. The UI does not require one specific USB form factor. A denied
high-risk action shows **보안키로 인증** and returns to the same `?page=...` view after Keycloak
step-up. DataRiver never replays the approval or publish request automatically; review it and click
the operation again. The local identity profile has no mobile-OTP setup step.

The two presentation/security switches are deployment settings, meaning values loaded by the API
process from this machine's ignored `.env` (or a production orchestrator/secret policy), not fields
that a signed-in browser administrator can lower during the protected action:

```dotenv
# Single-Workspace presentation; Workspace ABAC/RLS remains active.
WORKSPACE_SELECTION_ENABLED=false
# Optional. Disables DataRiver WebAuthn use and leaves WebAuthn-gated writes denied.
OIDC_HARDWARE_WEBAUTHN_ENABLED=false
```

After changing either value, recreate the API process so it reloads configuration:

```bash
docker compose -f compose.yaml up -d --force-recreate api
```

Silent access-token renewal keeps one API client and swaps only its request-time token. It no
longer recreates every feature client or causes a periodic screen-wide data reload; a failed
renewal still returns to explicit Sign In.

The `local-identity` bootstrap is rejected when `APP_ENV=production`. With an enterprise IdP, provision `(issuer, sub)` and a workspace membership through the controlled environment onboarding process; do not reuse local identities.

## Host-development quick start

Use this topology while API, workers and UI are changing frequently. PostgreSQL, the two Valkeys, SeaweedFS, Keycloak and APISIX stay in containers; Uvicorn, all four long-running backend relay/workers and Vite run directly from the checked-out source. The production-oriented base Compose remains private by default; `compose.host-dev.yaml` publishes only the required development ports on loopback.

Every repository Compose/host-development combination is a **Single-node Pilot**, even if multiple
processes run on that host. HA requires independent nodes, off-host distributed storage and accepted
failover/restore evidence; replica settings alone are not an HA claim (ADR-0013).

The v1 repository still does not own DataHub. The example below reuses a DataHub GMS already exposed on host port `8080`; replace both URLs and the scoped token when the external service is elsewhere.

Browser-visible auxiliary links are optional and independent of backend provider endpoints. Configure only the links that the deployment wants to expose with `UI_DATAHUB_URL`, `UI_AIRFLOW_URL`, `UI_GRAFANA_URL`, `UI_PROMETHEUS_URL`, and `UI_GRAPH_URL`. The API validates and publishes them through the authenticated capabilities response; it does not invent localhost defaults or return credentials. Production accepts HTTPS links only. Grafana remains a new-window link unless the deployment separately supplies matching exact-origin `GRAFANA_EMBED_BASE_URL`, explicitly enables `GRAFANA_EMBED_ENABLED`, records `GRAFANA_EMBED_EVIDENCE_REFERENCE`, and passes the same origin into the web CSP; the browser cannot enable embedding or provide a frame URL.

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

The launcher also supports this command when the checkout is reached through a WSL UNC path: it
maps only the Vite `npm.cmd` child to a temporary drive, because `cmd.exe` cannot use a UNC working
directory. Backend source processes keep their original checked-out path.

Start the gateway from WSL only after the Windows host API is live. The script discovers the current WSL-to-Windows gateway address:

```bash
./scripts/start_gateway_host_dev.sh
```

If the optional Airflow stack is running with host source processes, recreate its four long-running
services with the dedicated overlay after the gateway is ready. This keeps ordinary host-dev Compose
validation independent of Airflow while routing DAG calls through APISIX:

```bash
docker compose -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.host-dev.yaml -f compose.airflow.host-dev.yaml \
  up -d --force-recreate airflow-api-server airflow-scheduler \
  airflow-dag-processor airflow-triggerer
```

Open Vite at `http://localhost:5173`, API docs at `http://localhost:8000/api/docs`, Keycloak at `http://localhost:18081`, and APISIX at `http://localhost:9080`. Vite proxies `/api` through APISIX. Inspect or stop host processes with `./scripts/dev.ps1 status` and `./scripts/dev.ps1 stop`. Runtime PIDs and logs are written only below the ignored `runtime/host-dev/` directory.

The host process manager starts Uvicorn first and requires `/api/v1/health/ready` before starting
workers or Vite. It forces the Uvicorn file watcher to poll so a Windows host process reliably
reloads backend sources stored in the WSL filesystem before APISIX serves them. `/health/live` proves
only that the process is running; readiness also leases an API database connection and requires the packaged sole Alembic head. If readiness reports
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

# Optional local-only observability UI and OTLP backend on Grafana :3300,
# Prometheus :9090 and Alertmanager :9093. This is still Single-node Pilot.
docker compose -f compose.yaml -f aux-compose.yml --profile observability up -d --wait

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

## 운영 환경 업데이트 가이드

이 절차는 승인된 릴리스 커밋을 운영 PC의 기존 배포에 반영하기 위한 순서이다. 저장소의
기본 Compose는 **Single-node Pilot** 토폴로지이며 HA 운영 배포본이 아니다. 실제 운영은
[배포 운영 문서](docs/08_DEPLOYMENT.md)의 외부 OIDC, 별도 운영 DataHub, 백업·복구,
TLS, 이미지 digest 고정 및 승격 게이트를 먼저 충족해야 한다. `compose.identity.yaml`,
`compose.graph.yaml`, 관측성 Pilot 및 합성 시드는 로컬 전용이므로 운영 명령에 추가하지
않는다. 조직이 검토한 운영 overlay가 있다면 아래 모든 Compose 명령에 동일한 `-f` 목록을
일관되게 적용한다.

### 1. 변경 전 확인 및 코드 갱신

DB와 오브젝트 스토리지의 복구 지점을 생성하고 복구 가능성을 확인한 후 작업한다. `.env`,
`secrets/`, 런타임 볼륨은 배포 환경 소유이며 Git에서 복사하거나 덮어쓰지 않는다. 다음
`git status --short` 출력이 비어 있지 않으면 중단하고 운영 PC의 로컬 변경부터 보존한다.

```bash
cd /path/to/datariver_v1
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
git rev-parse --verify HEAD
```

승인된 릴리스 SHA와 마지막 출력이 같은지 확인한다. 운영 설정은 최소한
`APP_ENV=production`, HTTPS 외부 URL과 정확한 CORS origin,
`DATAHUB_VERSION_ENFORCEMENT=enforce`, 운영용 secret 파일 참조를 사용해야 한다.
고위험 CR/관리자 작업에는 `OIDC_HARDWARE_WEBAUTHN_ENABLED=true`를 유지하고, 별도의
Maker-Checker 승격을 완료하지 않았다면 `ADMIN_PASSWORD_FALLBACK_ENABLED=false`로 둔다.
브라우저의 시스템 설정을 런타임에 바로 반영하는
`SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED`도 운영에서는 활성화하지 않는다.

```bash
docker compose -f compose.yaml config --quiet
```

### 2. 이미지 준비와 DB 마이그레이션

정식 운영 배포는 CI에서 검증한 digest 고정 이미지를 받아야 한다. 현재 저장소를 직접
빌드하는 Single-node 운영 PC라면 다음 명령으로 동일 소스의 이미지를 먼저 준비한다.

```bash
docker compose -f compose.yaml build --pull
```

애플리케이션을 올리기 전에 권한이 분리된 `migrate` 서비스로 Alembic을 실행한다. 이
릴리스의 필수 revision은 `0038`이다. 호스트의 임의 DB 계정으로 `alembic`을 직접 실행하지
않는다.

```bash
docker compose -f compose.yaml run --rm migrate
docker compose -f compose.yaml run --rm migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current
```

두 번째 명령의 현재 revision이 `0038 (head)`인지 확인한다. 마이그레이션 실패 시 서비스를
재기동하거나 downgrade를 추측 실행하지 말고, 로그와 DB 상태를 보존한 채 배포를 중단한다.

### 3. API·Worker·Web 재기동과 상태 확인

마이그레이션이 성공한 뒤 기본 서비스를 재생성한다. Compose의 의존성도 `migrate` 성공을
요구하므로 이미 최신인 DB에서는 이 단계가 안전하게 재확인된다.

```bash
docker compose -f compose.yaml up -d --wait
docker compose -f compose.yaml ps
docker compose -f compose.yaml logs --since=10m \
  api outbox-relay upload-worker upload-validation-worker governance-apply-worker
```

운영 URL로 liveness와 readiness를 각각 확인한다. 아래 호스트명은 실제 TLS origin으로
바꾼다. liveness `200`만으로는 배포 성공이 아니며 readiness도 `200`이어야 한다.

```bash
curl --fail --silent --show-error \
  https://datariver.example.internal/api/v1/health/live
curl --fail --silent --show-error \
  https://datariver.example.internal/api/v1/health/ready
```

### 4. FIDO2/Keycloak 보증 계약 확인

대상 IdP가 운영자가 관리하는 Keycloak일 때만, 승인된 bootstrap 관리자 secret을 파일로
마운트한 관리 단말에서 다음 migration을 실행한다. 다른 IdP는 동일한 `acr`/`amr`/
`auth_time` 보증을 제공하는 공급자별 절차가 필요하다.

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

같은 명령에서 `--apply`만 제거해 read-only drift 검사를 다시 수행한다. 그 후 서로 다른
실사용 Developer, Data Steward, 전역 Admin으로 시스템 담당자를 확인하고, 브라우저에서
승인된 하드웨어 인증기를 사용한 FINAL step-up을 검증한다. 일반 password/direct-grant 및
service token의 FINAL 호출은 `401` 또는 `403`으로 차단되어야 한다. 로컬 전용
`scripts/e2e/run_cr_workflow.py`는 운영에서 실행하지 않는다.

### 5. 실패 시 처리

무조건적인 `alembic downgrade`나 볼륨 삭제는 금지한다. readiness 또는 핵심 워크플로우가
실패하면 신규 트래픽 승격을 중단하고 위 로그, 릴리스 SHA, migration revision을 보존한다.
이전 이미지로 되돌릴 수 있는지는 새 스키마와의 호환성을 먼저 확인해야 하며, 호환되지
않으면 승인된 복구 절차로 DB·오브젝트 저장소의 일관된 복구 지점을 사용한다.

## Main functional flows

- Catalog: an authorized local projection serves cursor-bound ALL-term search, facets, autocomplete and a lazy `platform -> database -> schema -> asset` Resource Tree before selected details are enriched through a fixed DataHub adapter. The result table shows source-backed Terms and Tags beside the asset identity, exposes a horizontal scroll region, and offers per-column ascending/descending sorting and text filtering over the currently loaded logical page. Logical page sizes 50/100/200/500/1000/All are composed by following the existing authorization- and policy-bound cursor in server batches of at most 100; this does not expand the API's bounded page contract. Database/schema hierarchy comes only from typed DataHub browse containers; the platform never invents it by splitting URNs. Tag/Term entry suggestions merge the authorized projection with a bounded, paged DataHub controlled-vocabulary search before applying the picker limit, so values outside a provider's first short page remain selectable. Provider failure safely falls back to the projection. Authorized detail keeps `Table Details` and a fixed-height, authorization-pruned local `Lineage` graph. The graph fits its detail-panel viewport, wraps each stage after three nodes without omitting nodes, and supports pan, node positioning and zoom. Selecting a node opens its authorized local detail; the external DataHub Lineage iframe is not invoked by this UI. A `sync_id`-bound full reconciliation is sequential, single-writer and tombstones missing DataHub-owned assets without touching seed-owned rows. Governed CSV/XLSX export is a server-managed, owner-scoped job bound to the exact query/filter, permission/classification-policy snapshot and projection watermark; toolbar buttons never synthesize a browser-side file. Export excludes RESTRICTED assets unconditionally, neutralizes spreadsheet formula injection, reauthorizes every download, and issues only a 60-second URL after object metadata reconciliation.
- Registration: browser multipart upload goes directly to quarantine storage. Table/column Tag and Term values remain on a one-line scrollable badge control with thin previous/next buttons; the compact `+` opens its vocabulary/new-proposal input directly below that control. Workers complete the object, stream SHA-256/size/format checks with bounded memory, copy to a validation-attempt-scoped accepted key, fully re-read the promoted bytes and delete quarantine only after the version-fenced database acceptance commits. The MANUAL workbench creates a dataset-description proposal only after a live DataHub preview, an opaque target/source-bound `If-Match`, server-side classification and a same-transaction target share lock. The BULK workbench explicitly separates format-only uploads from the bounded `DATASET_DESCRIPTION_CSV_V1` profile, can queue/read a server-configured preparation only from exact `ACCEPTED` byte evidence and renders real preparation state in the v0.3-style status tracker. A source-only bounded parser contract exists, but the isolated parser worker, candidate read/preview and proposal creation remain disabled, so READY preparation evidence is not presented as a change request or DataHub update and the browser exposes no raw proposal form.
- Change management: typed DataHub aspect UPSERT requests are server-bound to an authorized local dataset identity and scope, then move through legal transitions and distinct final approval. In new-CR intake, each Tag/Term `+` unions the bounded authorized projection with the fixed, bounded DataHub `*` controlled-vocabulary browse; keyword input narrows that same adapter query before a comma-aware new proposal is offered. Column input reserves the table Schema track, so column item/Type/Description/Term/Tag/requested-change/management align with Table/Owner/description/Terms/Tags/requested-change/column-addition above it. Reads use the current authorized target; approval and forward transitions reject identity, revision or authorization-scope drift. REVIEW and TEST require every routed System's Developer evidence, while FINAL requires every routed System's Developer and Data Steward plus one role-separated global Admin. Every FINAL decision also requires recent hardware-WebAuthn assurance. Generic raw Aspect creation and the legacy upload-derived raw proposal API additionally require the deny-by-default, hardware-human-only `change.raw.create` action and are not exposed in the ordinary UI. A leased worker applies each aspect idempotently and only marks `APPLIED` after re-read hash equality. Apply-time requester/policy reauthorization, DataRiver target serialization and external provider CAS remain explicit production gates.
- Classification access administration: eligible human security administrators can review and independently approve versioned four-class Search/Chat policies, review or revoke immutable inference-provider profile versions, and govern policy-bound RESTRICTED Search grants. ADR-0020 additionally permits an audited, read-only same-workspace catalog review of non-deleted quarantined DataHub projections for classification remediation, including the fixed typed DataHub metadata detail; it never enables export, Chat, arbitrary provider access or mutation. The Admin UI never accepts provider endpoints or credentials, and RESTRICTED evidence is never eligible for Chat.
- Knowledge graph: create a graph/ontology, author typed node/edge changesets, validate, independently review, publish or roll back immutable releases, export governed views and call bounded analysis. Raw SQL/Cypher is never accepted.
- API sharing: create a release-pinned contract version, publish it with recent strong authentication, grant an OIDC `client_id` explicit scopes/classification/validity and quotas, revoke it, and invoke bounded neighbor analysis through an atomic grant-and-usage check.
- Chat: deterministic baseline answers only from catalog or active-release knowledge evidence that passed prefiltering and per-item authorization. Immutable chunks bind workspace, classification, typed scope, source/version/effective time and content hash; only validated cited chunk IDs are persisted, otherwise the answer is `검증 불가`. Persistence additionally requires the workspace's independently approved ACTIVE retention policy: each new session binds its exact policy ID/hash and database-time deadline, and a superseded, expired or legacy-unbound session is append-closed. There is no duration fallback. The default inference-worker contract rejects SQL, Cypher, arbitrary HTTP, tools and mutation fields. The sole exception is the explicit Mac-development adapter in [ADR-0023](docs/adr/0023-mac-development-local-inference-and-graph-projection.md): native Ollama receives a fixed non-executable answer/citation function and its untrusted result remains subject to the existing validation. External inference remains disabled until live revalidation, delivery/streaming, metrics and scaled red-team gates are accepted.
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

### Large external value-chain seed and DataHub lineage

For catalog-scale and lineage testing, use the separate, restartable external seed workflow in
[the semiconductor seed workflow](docs/17_SEMICONDUCTOR_SEED_WORKFLOW.md). It is deliberately
separate from the small in-application reference seed above: it writes only the dedicated
`semiconductor_seed` PostgreSQL schema, never DataRiver business tables.

The local command creates 500 PostgreSQL tables, 500 PostgreSQL views, 20 deterministic rows per
table by default, a labelled Oracle **MOCK** DDL artifact, and 2,000 DataHub dataset entities when
the `dual` scope is selected. The schema is reset only after explicit confirmation and refuses to
remove unexpected objects.

On the validated Mac Compose topology, trigger the same bounded workflow through Airflow after the
core stack is healthy. It is manual-only and has no schedule. `docker compose exec` does not invoke
the service entrypoint automatically, so retain the wrapper below: it loads the Airflow database
and API secrets from their mounted files without exposing them in the command or shell history.

```bash
docker compose -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags unpause datariver_semiconductor_seed_ingestion
docker compose -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags trigger datariver_semiconductor_seed_ingestion
# After the run is SUCCESS, return the manual-only DAG to its default pause state.
docker compose -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags pause datariver_semiconductor_seed_ingestion
```

```powershell
# Run from the repository root after the host-development dependencies are healthy.
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py `
  --apply --confirm-reset --ingest-datahub --entity-scope dual
```

`--ingest-datahub`는 controlled semiconductor Glossary·Tag를 먼저 UPSERT하고 테이블 및
실제 PostgreSQL 컬럼의 Term/Tag를 함께 적용한 뒤 read-back 검증합니다. 물리 데이터 생성
없이 vocabulary만 먼저 초기화·검증하려면 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py --seed-governance
```

The command reads the local PostgreSQL owner password and DataHub token only from ignored secret
files, writes its evidence only below ignored `runtime/semiconductor-seed/`, and verifies the exact
generated DataHub entity count through the typed aspect-read endpoint. It also provisions a
controlled semiconductor glossary/tag hierarchy and applies family, scenario, provenance, stage,
execution, and platform metadata to every generated dataset plus field semantics to PostgreSQL,
view and clearly labelled Oracle MOCK fields. It never prints a secret. The vocabulary-only initialization and read-only verification
commands are in [the semiconductor governance taxonomy](docs/18_SEMICONDUCTOR_GOVERNANCE_TAXONOMY.md).
Use the paused-on-creation `datariver_semiconductor_seed_ingestion` Airflow DAG for repeatable
manual runs; see the workflow document for its bounded resource settings and trigger procedure.
`infra/datahub/recipes/semiconductor_postgres.yml` is the separate native DataHub CLI recipe for a
real PostgreSQL source inspection. Do not use its Oracle companion as an Oracle source recipe: it
is intentionally a MOCK metadata manifest.

## Source verification

```bash
uv sync --frozen --all-extras
uv run ruff format --check backend/src backend/tests infra/airflow/dags
uv run ruff check backend/src backend/tests infra/airflow/dags scripts/configure_keycloak_assurance.py scripts/generate_initial_migration.py scripts/generate_semiconductor_seed.py scripts/probe_pgbouncer_rls.py scripts/probe_policy_revocation.py scripts/verify_datahub_contract.py scripts/verify_datahub_image_inventory.py scripts/verify_static.py
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
# `runtime/` is ignored: render this JSON from the independently operated DataHub deployment.
uv run python scripts/verify_datahub_image_inventory.py runtime/datahub-rendered.compose.json
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
