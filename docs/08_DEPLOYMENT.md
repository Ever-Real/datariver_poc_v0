# Deployment and operations definition

## Implemented Compose topology

All repository Compose overlays and the hybrid host-development shape are labeled **Single-node
Pilot**. They are not HA, regardless of local replica count. An HA environment is an external
deployment promotion that satisfies ADR-0013: at least three independent hosts/VMs, off-host
replicated/distributed storage, end-to-end failure-domain review and accepted failover/restore
evidence.

| File/profile | Components | Boundary |
|---|---|---|
| `compose.yaml` | PostgreSQL 17.10, two Valkey 9.1 instances, SeaweedFS 4.39, migration/storage init, API, UI, outbox relay, upload completion/validation and governance apply workers | portable core |
| `compose.identity.yaml` | Keycloak 26.7 and isolated Keycloak database/credentials | local identity only |
| `compose.source-host.yaml` | loopback host ports and a dedicated publication bridge for PostgreSQL, the two Valkey instances and SeaweedFS | source-host development; does not assume a DataHub Docker network |
| `compose.airflow.yaml` | Airflow 3.3 API server, scheduler, DAG processor, triggerer and init using LocalExecutor/isolated DB role | scheduled scan/probe only |
| `compose.gateway.yaml` | APISIX 3.17 standalone configuration | local gateway/rate limit/health-check profile |
| `compose.graph.yaml` | Neo4j Community projection sandbox | local only; PostgreSQL KG releases remain canonical |
| `aux-compose.yml` + `observability` profile | OTel Collector, Prometheus, Grafana, Alertmanager, Tempo and Loki | optional Single-node Pilot telemetry backend; not an HA or production evidence claim |
| `semiconductor-seed` profile | deterministic one-shot seed command | explicit non-production data |

Production and shared environments do not start DataHub from this repository. For the validated Mac
development PC only, `scripts/start_datahub_mac_dev.sh` starts the official DataHub v1.6.0
Apple-Silicon `without-neo4j` composition from the ignored `runtime/datahub-v1.6.0` source checkout.
It is isolated from the DataRiver Compose project and uses its own volumes and generated token
service secrets. DataHub lineage never uses the separate `compose.graph.yaml` Neo4j service.

The current example DataHub provider contract is stable `v1.6.0`. Each deployment provides its own
exact stable `DATAHUB_EXPECTED_VERSION` and reviewed component OCI index digest contract (the current
example is [`infra/contracts/datahub-v1.6.0-images.json`](../infra/contracts/datahub-v1.6.0-images.json)).
An external owner may temporarily set `DATAHUB_ALLOWED_VERSIONS` to a reviewed numbered RC of that
same exact release, such as `v1.6.0rc1` for `v1.6.0`; it is an operational compatibility exception,
not a replacement stable contract or a mutable image tag. `head`, `latest`, partial versions and a
different release line remain invalid. DataRiver production sets
`DATAHUB_VERSION_ENFORCEMENT=enforce`. In development, an explicitly allowed compatible release
candidate such as `v1.6.0rc1` is treated as available rather than surfacing a
`VERSION_MISMATCH` capability; connection and authorization failures still remain visible. This
development exception does not change the production version contract.

During promotion, the external DataHub owner renders its own Compose deployment and proves both its
images and runtime endpoint. The v1 repository deliberately does not add an incomplete DataHub
stack just to own these images.

```bash
# At the external DataHub deployment repository, after all overrides are merged.
docker compose -f <datahub-compose-files> config --format json \
  > runtime/datahub-rendered.compose.json

# From DataRiver, this fails on an absent component, tag-only image, or a different digest.
uv run python scripts/verify_datahub_image_inventory.py \
  runtime/datahub-rendered.compose.json
uv run python scripts/verify_datahub_contract.py \
  --base-url <target-datahub-url> \
  --expected-version "$DATAHUB_EXPECTED_VERSION"
```

A successful image/version check is only the first gate; the live provider contract tests listed
below remain mandatory.

## Configuration and bootstrap

Bootstrap requires a DataHub token and generates ignored, permission-restricted secret files plus `.env` and the runtime Keycloak realm:

```bash
./scripts/bootstrap.sh '<datahub-token>'
# or: ./scripts/bootstrap.ps1 -DataHubToken '<datahub-token>'
```

Bootstrap is idempotent for infrastructure credentials: an existing non-empty secret is preserved, while the supplied DataHub token and derived SeaweedFS/Keycloak files are refreshed. Deliberate credential rotation follows the runbook and is not coupled to ordinary bootstrap.

### Mac development topology

Use `./scripts/bootstrap.sh --mac-development` only for the local Mac developer PC. It configures
loopback ports that avoid common local conflicts, points container-to-DataHub traffic to
`host.docker.internal:8080`, enables the native macOS Ollama bridge at its exact local OpenAI
compatible endpoint, and generates a secret-backed Neo4j password. If no DataHub credential exists,
the mode creates an ignored random placeholder because the bundled local DataHub composition has
authentication disabled; it is never valid for an external DataHub.

Docker Desktop is budgeted at 20 GiB/6 CPUs. Ollama stays native on the Mac host, so the selected
`datariver-gemma4-dev:0.1` model is outside Docker's memory limit. It reuses the
`gemma4:e2b-it-qat` weights but fixes its active context at 8,192 tokens through the checked-in
Modelfile. The full normal stack, DataHub and Neo4j fit this budget; do not run a duplicate Ollama
container. `compose.graph.yaml` attaches Neo4j
to the private `data` network for internal access and to an otherwise empty non-internal bridge
solely because Docker Desktop cannot publish loopback ports from an `internal: true` network. Its
HTTP/Bolt bindings remain `127.0.0.1:17474` and `127.0.0.1:17687`.

The source-host overlay applies the same boundary to PostgreSQL, both Valkey instances and
SeaweedFS: their canonical container path remains the internal `data` network, while an otherwise
empty non-internal `source-access` bridge permits only the explicitly declared `127.0.0.1` port
bindings. The bridge is not a provider or application service network and must not gain unrelated
members.

The local Ollama adapter is development-only and is enabled only for
`http://host.docker.internal:11434/v1`, `datariver-gemma4-dev:0.1`, a fixed 8,192-token context
and a 60-second timeout. `scripts/prepare_ollama_mac_dev.sh` creates that local derivative from
the checked-in Modelfile. It submits only a fixed non-executable answer/citation function and
validates its output as untrusted evidence. It does not make the model a production provider.
Neo4j is a rebuildable projection sandbox until a future verified release-projection adapter
exists; do not write DataRiver canonical state to it. The full decision and promotion limits are
in [ADR-0023](adr/0023-mac-development-local-inference-and-graph-projection.md).

ADR-0030 adds a separate development-only bridge for an authenticated model server operated on the
private corporate network. It is not an external commercial-provider route: the endpoint must be
HTTPS `/v1`, match the operator's exact host allowlist, resolve only to private non-loopback
addresses and use a mounted API-key secret. Chat and Embedding profiles are activated separately;
both are required with Neo4j for the Knowledge pipeline. Compose mounts the two optional API-key
secrets into the API process only. Production keeps this bridge disabled, and no provider endpoint,
credential or allowlist is browser-controlled.

Set `DATAHUB_BASE_URL` and review origins/ports in `.env`. Optional `UI_DATAHUB_URL`, `UI_AIRFLOW_URL`, `UI_GRAFANA_URL`, `UI_PROMETHEUS_URL`, and `UI_GRAPH_URL` values populate the GNB auxiliary links through the authenticated capabilities response. They are not provider API endpoints or embed authorities: URLs with user information are rejected, missing values create no fallback link, and production requires HTTPS. The production validator rejects wildcard CORS, HTTP external URLs, password-bearing URLs and seed activation. Only `file:` secret references are implemented; a Vault/KMS adapter is a separate deployment integration.

`WORKSPACE_SELECTION_ENABLED=false` selects the server-verified default Workspace and hides manual
switching; it never disables Workspace request scope, ABAC or RLS. The default must exist or the UI
fails closed. `OIDC_HARDWARE_WEBAUTHN_ENABLED=false` removes DataRiver enrollment/step-up entry
points and makes the API verifier refuse `HARDWARE_WEBAUTHN` assurance. It does not enable a
password downgrade, so direct high-risk mutations remain unavailable. These are operator-owned
process settings, not browser-editable administrator records. Recreate the API container after a
change so `/auth/me` and token verification share the same configuration.

`SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=true` plus an explicit
`SYSTEM_CONFIGURATION_RUNTIME_WORKSPACE_ID` enables ADR-0028 only in development. SAVE and TEST do
not alter runtime clients. ACTIVATE records the selected exact revision, and API/relevant workers
load it once on restart using their own existing RLS-scoped database role. The selected secret
references must name files actually mounted into every consuming process. The API-loaded version is
observable in Admin; worker restart success must be checked from the worker process/health evidence
and is never inferred from the API. Do not enable this resolver in production.

When the host-development overlay connects to a separately composed local DataHub stack, it uses
the deployment-owned external `DATAHUB_DOCKER_NETWORK` (default `datahub_network`) and overrides
container callers with `DATAHUB_CONTAINER_BASE_URL` (default `http://datahub-gms:8080`). This avoids
depending on a host-gateway route from a container. Source processes run directly on the host keep
using `DATAHUB_BASE_URL`; no browser receives the DataHub service token.

`DATAHUB_EMBED_ENABLED` remains `false` by default. Set it to `true` together with an exact-origin
`DATAHUB_EMBED_BASE_URL` only after DataHub's own browser identity mapping, object authorization,
`frame-ancestors` policy and the DataRiver CSP configuration have been tested. The API authorizes the
asset first, then builds `/dataset/{encoded-URN}/Lineage` itself; the browser supplies only an opaque
asset ID and never constructs an external URL. The frame is sandboxed, no-referrer and has a
new-tab fallback. A failed provider framing policy remains an unavailable capability, never a
localhost fallback.

`scripts/bootstrap.ps1 -DataHubEmbedOrigin '<exact-origin>'` (or the matching shell bootstrap
option) enables the catalog node-detail modal to frame the actual deployment-owned DataHub Lineage
page. The in-app Lineage tab remains a separately authorization-pruned typed graph. The API first
authorizes the opaque local asset ID and constructs the provider path itself; it never bridges a
DataRiver login or DataHub service token into the frame. DataHub must independently provide the
browser SSO/guest/session and `frame-ancestors` policy. The value is deployment configuration,
not a provider token, and never relaxes DataHub asset authorization.

A default viewer username/password must not be added to DataRiver source, environment-visible
browser configuration or an iframe URL. If anonymous read access is appropriate, the DataHub
operator configures its own least-privilege guest identity and browser entry policy; otherwise the
viewer signs in through DataHub's own SSO session. Both options require an operator-owned DataHub
authorization and framing acceptance test.

Grafana is a direct server-validated link by default. To embed it, set the full approved dashboard
page in `UI_GRAFANA_URL`, set `GRAFANA_EMBED_BASE_URL` to that URL's exact scheme/host/port origin,
then set `GRAFANA_EMBED_ENABLED=true` and record the SSO, `frame-ancestors` and CSP review in
`GRAFANA_EMBED_EVIDENCE_REFERENCE`. The web Compose service feeds the same origin to CSP
`frame-src`; configuration validation rejects missing evidence, a path/query on the origin, or an
origin mismatch. The resulting frame is sandboxed and no-referrer. There is no browser endpoint to
save, test or override either URL, so an unreviewed dashboard remains a new-window link.

Static validation and start:

```bash
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml up -d --build --wait
```

All local overlays can be validated and started as one model:

```bash
docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml config --quiet
docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
```

The observability services are an explicit opt-in profile. They bind their three UIs to loopback
only, generate the Grafana bootstrap password in the ignored `secrets/` directory, and do not get
the API's OIDC token or DataHub secret:

```bash
docker compose -f compose.yaml -f aux-compose.yml --profile observability config --quiet
docker compose -f compose.yaml -f aux-compose.yml --profile observability up -d --wait
```

The overlay provides the approved telemetry backends and an OTLP intake boundary. It does **not**
scrape the ABAC-protected DataRiver `/operations/metrics` endpoint with an administrator token, and
it does not claim application tracing is already installed. A target deployment must provision a
least-privilege scrape/OTLP identity, reviewed instrumentation, redaction test evidence, dashboards,
alerts and a retention plan before signals are used operationally. The collector configuration
removes authorization, SQL, prompt, evidence, URN and object-key attributes before export; this is
a guardrail, not a substitute for source-side minimization. For an existing enterprise telemetry
platform, use the reviewed deployment-owned OTLP exporter pattern in
[`infra/observability/otel-collector.enterprise.example.yaml`](../infra/observability/otel-collector.enterprise.example.yaml);
the checked-in Pilot config never embeds an enterprise endpoint or credential.

For local Keycloak, merge `compose.identity.yaml` and run the non-production identity bootstrap described in the root README. Enterprise identity deployments provision workspace/subject attributes through controlled environment onboarding.

An imported clean realm already contains the managed LoA flow. Because Keycloak import does not
update an existing realm, migrate and verify an existing deployment through the Admin API:

```bash
uv run python scripts/configure_keycloak_assurance.py \
  --base-url https://identity.example.internal \
  --admin-username '<bootstrap-admin>' \
  --admin-password-file /run/secrets/keycloak_admin_password \
  --username '<managed-security-admin>' \
  --configure-step-up --revoke-user-sessions --apply
```

The command constructs the unbound flow first, re-reads every execution and authenticator config,
and binds it only after verification. A same-name drifted flow is not overwritten. Ordinary login
uses password LoA 1; an explicit LoA 2 request requires WebAuthn with max age zero. The WebAuthn
registration action is enabled but not a default user action, so no mobile OTP or universal first-
login security-key enrollment is introduced. The web client is also attached to Keycloak's built-in
`basic` scope after its `AUTH_TIME` session-note mapper is verified, ensuring the access token has
the actual authentication time required by the backend. Target deployments must separately test browser PKCE,
key enrollment/revocation, spare-key recovery, RP ID/origins and any organization-approved
attestation/AAGUID policy.

The optional administrator password fallback remains disabled by default. Do not set
`ADMIN_PASSWORD_FALLBACK_ENABLED=true` until the target workspace has at least two real, active,
RESTRICTED-cleared human `security-administrators` with `admin.manage`, the IdP password
reauthentication redirect uses `max_age=0`, and the full maker-checker-consume browser/API journey
has passed. Local bootstrap intentionally does not manufacture a second administrator.

## Network and identity rules

- Core container defaults remain web `8080`, API `8000` and Keycloak `8081`. Host-development uses Vite `38102`, source API `38101`, Keycloak `18081`, APISIX `9080` and Airflow `8082` when their overlays are enabled.
- PostgreSQL, Valkey and object-service internals stay on the private `data` network and have no host bind in the core file.
- API has an RLS-constrained database role; migration owns DDL. Relay, upload, governance and bootstrap have distinct least-privilege database identities and service-specific secret mounts. Airflow and Keycloak have distinct databases/roles.
- APISIX standalone mode has no administration/control port and does not replace application ABAC.
- APISIX and web run non-root with read-only root filesystems. APISIX renders configuration and request temp files only into bounded, non-executable tmpfs; its health check executes a real proxied HTTP request rather than trusting a process-only command. Its declarative upstream uses APISIX DNS discovery through Docker's embedded resolver, so replacement of the API container does not pin a stale startup address.
- Web Nginx uses Docker's embedded DNS resolver for the API upstream. API container replacement therefore does not require web restart and must be included in recovery acceptance.
- Production exposes only a TLS edge. Direct local API/identity ports must be removed or firewalled by the environment override.

## Worker correctness

- PostgreSQL outbox is canonical. Relay publishes IDs to queue Valkey; failed events are individually retried, dead-lettered after the configured maximum and exposed in operations. Published outbox and completed inbox rows are not automatically pruned until the governed WORM/Legal-Hold/Maker-Checker retention gate is implemented and accepted.
- Cache Valkey has bounded volatile memory and `allkeys-lfu`; queue Valkey is separate, `noeviction`, AOF-backed. They never share a URL/database.
- Upload completion reconciles an already-completed multipart operation via object `HEAD`. Validation streams chunks and promotes with copy-before-manifest-commit; a stale quarantine duplicate is safe to clean later.
- Governance application uses a PostgreSQL job/attempt lease. Transient DataHub failures back off automatically; terminal/mismatched content reaches `APPLY_FAILED` and requires authorized requeue.
- Catalog export is disabled by default. Enable the `catalog-export` Compose profile only after
  bootstrap creates its independent credentials with `-EnableCatalogExportWorker`. It uses an
  independent NOBYPASSRLS database principal and independent non-admin S3 identity, enumerates only
  workspace identifiers before
  setting transaction-local workspace context, and receives no DataHub credential or egress. Each
  attempt uses a distinct object key; only the current unexpired lease can publish its receipt.

## Airflow boundary

All included DAGs are paused at creation. `datariver_catalog_probe` performs a read probe;
`datariver_catalog_sync` calls the versioned page-sync API; and
`datariver_manual_metadata_apply` asks DataRiver to claim one bounded MANUAL CSV receipt at a time.
The last DAG has neither a DataHub nor an object-store credential: DataRiver streams/hash-checks the
private receipt and owns typed provider read–merge–read-back. The semiconductor ingestion DAG runs
the same bounded reconciliation after its DataHub emission. `DATARIVER_API_BASE_URL` is
deployment-owned: the container topology uses `http://api:8000`, while the optional
`compose.airflow.host-dev.yaml` overlay uses `http://apisix:9080` so Airflow shares the gateway's
dynamically discovered WSL-to-host API route. Keep this overlay separate from
`compose.host-dev.yaml`, which must remain valid without Airflow. Bootstrap creates the confidential
`datariver-airflow` Keycloak client and its mounted client
secret. Tasks obtain and refresh short-lived `client_credentials` tokens; no long-lived bearer token
is stored. The application membership grants only `catalog.search`, `catalog.read` and `catalog.sync`
for the selected workspace.

The Compose overlay intentionally uses Airflow `SimpleAuthManager` only for loopback development and pre-creates its password file from a secret. Any shared or production deployment must replace it with an environment-supported enterprise/FAB SSO configuration and retest authorization; the DataRiver service-token flow is independent of that human UI login choice.

## Database and object operations

- Alembic has one head at `0034`: the generated current initial schema plus conditional compatibility bridges for local databases that applied earlier revisions. Deployment runs migration before API/workers. The API role can only read `public.alembic_version` for readiness; migration ownership remains separate. Clean-install bridges validate complete canonical objects, execute only when the feature contract is absent, and reject partially present schemas.
- PostgreSQL pool size/overflow/lease timeout, statement timeout, idle-transaction timeout and application names are explicit. Budget `API replicas × (API pool + overflow) + long-running workers × (worker pool + overflow) + one-shot/IdP/Airflow/admin reserve`; current one-API/four-worker defaults have a ceiling of 60 before reserve.
- Liveness is process-only. Readiness leases the API pool and requires exactly packaged Alembic head `0034`; Compose and APISIX use readiness for upstream health.
- `scripts/probe_pgbouncer_rls.py` and its unit contract implement the pre-adoption transaction-pool leakage gate. No Compose profile currently deploys PgBouncer and no live pooler pass has been recorded; direct PostgreSQL remains the supported path until the isolated two-workspace probe succeeds.
- Back up PostgreSQL and SeaweedFS as a consistency set or record a watermark; restore into isolation and follow the drill in [operations runbook](13_OPERATIONS_RUNBOOK.md) before traffic.
- Accepted-object retention/lifecycle is environment policy. Quarantine receives a shorter cleanup policy, but never delete an object whose manifest is actively leased.
- Initial recovery targets (RPO <= 5 minutes, RTO <= 60 minutes) are objectives until an environment drill records measured evidence.

The assistant inference module is not a production runtime component. It has a disabled adapter and
a typed pre-authorized input/output contract only; Compose creates no inference queue/job. The
development-only exceptions in ADR-0023 and ADR-0030 use a fixed non-executable cited-answer
contract, not a Chat production route. Provider integration, durable dispatch, SSE, pre/post-call
live policy/profile revalidation and operational metrics remain promotion gates.

## Release gates

CI verifies backend format/lint/types/tests, frontend type/lint/tests/build, generated migration consistency, DAG/shell compilation, dependency audit, Trivy source/IaC and backend/frontend image scans, CycloneDX SBOM generation and Compose static configuration. A production candidate additionally requires:

1. runtime Compose/Kubernetes smoke test with the target DataHub/OIDC/object implementation;
2. migration upgrade, backup/restore and worker crash/retry drills;
3. ABAC cross-workspace/clearance matrix and strong-auth approval test;
4. DataHub scan/detail/apply/re-read contract fixtures for its deployed version;
5. object multipart/copy/checksum/CORS conformance;
6. load/resource results, SBOM/license inventory, secret/SAST/dependency/image scans;
7. signed acceptance report with unresolved exceptions and expiry.

Image tags are exact in development manifests; production promotes digest-pinned images. `latest` is forbidden. Major dependency upgrades require an ADR, migration rehearsal and rollback evidence.

SeaweedFS remains the local/Pilot upload implementation. `application.ports.ObjectStore` is the
provider-neutral S3 boundary and `infrastructure.object_store.S3ObjectStore` uses only that S3
contract, so an existing MinIO-compatible endpoint can be selected by deployment configuration
without changing use cases. Immutable archive production promotion uses the separate port and
evidence gate in ADR-0012; no checked-in product label or Object Lock setting is treated as WORM
acceptance.

## Failure behavior

| Failure | Expected behavior |
|---|---|
| DataHub | local authorized search/monitoring remain; enrichment/apply/sync degrade; no false `APPLIED` |
| cache Valkey | higher latency only |
| queue Valkey | outbox accumulates; relay later recovers delivery |
| object store | upload unavailable; catalog/change/KG remain |
| Airflow | scheduled sync/probe delayed; interactive paths remain |
| Keycloak/OIDC | protected requests fail authentication; public liveness remains |
| optional gateway | core loopback API remains available only where deployment policy allows |
