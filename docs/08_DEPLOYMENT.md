# Deployment and operations definition

## Implemented Compose topology

All repository Compose overlays and the hybrid host-development shape are labeled **Single-node
Pilot**. They are not HA, regardless of local replica count. An HA environment is an external
deployment promotion that satisfies ADR-0013: at least three independent hosts/VMs, off-host
replicated/distributed storage, end-to-end failure-domain review and accepted failover/restore
evidence.

| File/profile | Components | Boundary |
|---|---|---|
| `compose.yaml` | PostgreSQL 17.10, migration/optional external-storage init, API, UI, outbox relay, upload completion/validation and governance apply workers; opt-in catalog-export and retention-archive workers; explicit external connector network | portable DataRiver core; no Redis or object-store provider is bundled |
| `compose.identity.yaml` | Keycloak 26.7 and isolated Keycloak database/credentials | local identity only |
| `compose.source-host.yaml` | loopback host port and a dedicated publication bridge for PostgreSQL | source-host development; does not publish external connector services |
| `compose.connected-source-host.yaml` | registry-disabled local PostgreSQL and final Keycloak references | pre-state rapid source validation only; never release evidence or rebuild identity |
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

## Offline Python dependency cache

The lockfile records dependency versions and hashes, but it intentionally does not commit package
artifacts. A connected build host with the same target OS, CPU architecture, Python 3.12 and uv
0.9.17 creates a checksum- and manifest-backed cache archive with
`scripts/export_offline_python_cache.sh`. The script verifies a clean `uv sync --frozen
--all-extras --offline` from the archive before release. Transfer the archive through the approved
artifact channel, verify its SHA-256 sidecar and unpack its `uv/` directory under the target user's
cache parent (normally `$HOME/.cache`) before running the frozen offline sync. Do not commit the
archive, copy a cache across platforms or rely on an unverified cache from a different lockfile.

## DataHub reconciliation deletion gate

Catalog refresh uses DataHub `scrollAcrossEntities`; it does not use mutable numeric provider
offsets. The opaque scroll cursor stays in `catalog.sync_runs` and never crosses the public API.
DataHub v1.6 has point-in-time creation disabled by default, so an image or API version match is not
evidence that missing assets may be treated as deleted.

Keep these defaults in every new Mac/arm64 and WSL/linux-amd64 environment:

```dotenv
DATAHUB_CATALOG_PIT_VERIFIED=false
DATARIVER_CATALOG_SYNC_MAX_PAGES=10002
```

With the default, a complete run refreshes present rows and reports
`SUPPRESSED_UNVERIFIED_SNAPSHOT`; it does not tombstone missing rows. Enable deletion only after the
external DataHub owner has proved PIT support for the exact Elasticsearch/OpenSearch runtime and
accepted a live test covering concurrent add/delete, cursor expiry, response-loss replay and
exact-multiple terminal paging:

```dotenv
DATAHUB_VERSION_ENFORCEMENT=enforce
DATAHUB_CATALOG_PIT_VERIFIED=true
DATAHUB_CATALOG_PIT_EVIDENCE_REFERENCE=ops://datahub/pit/accepted-run-id
```

All three values are required. `report` mode cannot be combined with verified PIT. A changed
DataHub/search-backend version or topology invalidates the evidence and requires the gate to return
to `false` until reaccepted. `DATARIVER_CATALOG_SYNC_MAX_PAGES` accepts `1..100002`; the default
supports one million assets at 100 per page plus an empty terminal probe. See
[ADR-0040](adr/0040-datahub-scroll-pit-reconciliation.md).

Each verified run forces a fresh provider-version probe on page zero and stores the evidence
reference, observed version and a SHA-256 bound to the normalized DataHub origin and fixed scroll
contract. Changing an endpoint or scan contract therefore changes the run authority; an ordinary
cached capability probe is not accepted as deletion evidence.

Each Airflow attempt first reads `GET /catalog/sync/datahub/{sync_id}` and resumes from the persisted
public page ordinal; it does not replay every earlier page and consume the five-minute provider
cursor keepalive. A completed run returns immediately, while an abandoned run requires a new DAG run
and therefore a new deterministic `sync_id`. DataRiver holds a transaction-scoped workspace
reconciliation reservation across each bounded DataHub call and commit. A non-configurable 10-second
provider budget covers queue wait, a page-zero version probe, GraphQL and every adaptive retry
together; it is deliberately below both the runtime PostgreSQL 15-second statement timeout for a
waiting duplicate lock and its 30-second `idle_in_transaction_session_timeout`. Expiry rolls back
the reservation and returns a retryable dependency error. Size the API connection pool for the
approved number of concurrent workspace syncs. If a provider response exceeds the 8 MiB transport
boundary, the API retries the same cursor with page sizes `100 -> 50 -> 25 -> ... -> 1`; a single
entity that still exceeds the boundary fails closed and requires provider/schema remediation.

## Configuration and bootstrap

Bootstrap generates ignored, permission-restricted secret files plus `.env` and the runtime Keycloak
realm. A DataHub token is supplied when that connector is enabled:

```bash
./scripts/bootstrap.sh --datahub-token-file /approved-secure-transfer/datahub_token
# PowerShell: ./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'
```

Bootstrap is idempotent for infrastructure credentials: an existing non-empty secret is preserved,
legacy Valkey secret filenames are copied to the canonical Redis filenames when necessary, and a
supplied DataHub token plus derived Keycloak files are refreshed. Deliberate credential rotation
follows the runbook and is not coupled to ordinary bootstrap.

On Unix/WSL, bootstrap uses owner-only creation and a `0700` secrets parent before Compose
materializes file secrets. Native Windows PowerShell disables inherited ACLs on the secrets and
Keycloak-runtime directories/files and grants only the current identity and `SYSTEM`. Copying these
files elsewhere is a new security boundary and requires an ACL review.

Managed installation never infers Mac from the checkout host. Select one explicit profile:

| Profile | Supported Docker platform | Selected environment file | Purpose |
|---|---|---|---|
| `portable-development` | `linux/arm64`, `linux/amd64` | `.env.portable-development` | general source build; no inference default |
| `mac-development` | `linux/arm64` | `.env.mac-development` | reviewed Mac local-integration compatibility |
| `wsl-preparation` | `linux/amd64` | `.env.wsl-preparation` | verified offline WSL preparation |

The fresh workflow records the exact selected environment path in its ignored applied-state file.
The update workflow reuses it, and the Compose wrapper passes it both to interpolation and container
`env_file`. A normal clean clone should begin with `portable-development`; the Mac profile is not a
universal default.

```bash
./scripts/workflow_fresh_setup.py \
  --profile portable-development \
  --datahub-mode external \
  --datahub-base-url https://<approved-datahub-gms-host> \
  --datahub-token-file /approved-secret-path/datahub_token \
  --redis-mode local \
  --storage-mode local \
  --airflow-mode skip
```

### Bootstrap dependencies and connector inventory

PostgreSQL and an OIDC issuer are bootstrap capabilities: the API cannot read a database-backed
configuration before they work. PostgreSQL is the only stateful dependency owned by the base
Compose; `compose.identity.yaml` provides an optional local Keycloak implementation of OIDC.
Redis cache/delivery, S3/MinIO, DataHub, Airflow, Neo4j, LLM and observability are external or
opt-in feature connectors.

Initial deployments set endpoints and mounted-secret references in `.env`. The authenticated System
Settings inventory classifies entries as `BOOTSTRAP_REQUIRED`, `CORE_CONNECTOR` or
`FEATURE_CONNECTOR` and returns every required connection field with a `secret` flag. It is
read-only and can run only server-owned probes against the API's loaded deployment snapshot.
Operators edit the selected ignored environment and mounted secrets, then apply them through the
matching update/restart workflow.

Durable Knowledge PDF analysis is an independent opt-in capability. It requires Chat and Embedding
readiness, but not Neo4j. The API continues to serve the core platform when
`KNOWLEDGE_SOURCE_WORKER_ENABLED=false`; it reports the capability unavailable and rejects a new
analysis enqueue before creating a permanent queue item. The `knowledge-source` Compose profile
starts only the purpose-bound worker and does not activate a graph projection.

Bootstrap validates inference settings before enabling the worker, so use two passes:

```bash
# Mac arm64: configure/probe LOCAL_OLLAMA_EMBEDDING_* after the first pass.
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development \
  --enable-knowledge-source-worker

# WSL linux/amd64: configure/probe private INTRANET_OPENAI_COMPATIBLE_CHAT_* and
# INTRANET_OPENAI_COMPATIBLE_EMBEDDING_* after the first pass.
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --datahub-token-file /approved-secure-transfer/datahub_token
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --enable-knowledge-source-worker

# Native Windows PowerShell operates on .env.
./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'
./scripts/bootstrap.ps1 -EnableKnowledgeSourceWorker
```

The WSL/private OpenAI-compatible provider, external S3 IAM, real browser, representative load and
target amd64 execution checks remain `EXTERNAL_GATE`; source/unit checks on the arm64 Mac cannot
close them.

### Mac development topology

Use `./scripts/bootstrap.sh --mac-development` only for the local Mac developer PC. It configures
the same developer-facing web `38102` and API `38101` port contract as source-host development,
keeps the host PostgreSQL binding on conflict-resistant `15432`, and points
container-to-DataHub traffic to
`host.docker.internal:8080`. Local model capabilities remain disabled until the operator selects
already installed model IDs in `.env.mac-development`; bootstrap never creates or selects one.
The profile also generates a secret-backed Neo4j password. If no DataHub credential exists,
the mode creates an ignored random placeholder because the bundled local DataHub composition has
authentication disabled; it is never valid for an external DataHub.

Docker Desktop is budgeted at 16 GiB/6 CPUs by default, or at most 18 GiB for a bounded large
import. Ollama stays native on the Mac host and remains outside Docker's memory limit. Choose an
already installed model that leaves unified-memory headroom; do not create a repository-specific
derivative or run a duplicate Ollama container. `compose.graph.yaml` attaches Neo4j
to the private `data` network for internal access and to an otherwise empty non-internal bridge
solely because Docker Desktop cannot publish loopback ports from an `internal: true` network. Its
HTTP/Bolt bindings remain `127.0.0.1:17474` and `127.0.0.1:17687`.

The source-host overlay applies this boundary only to PostgreSQL: its canonical container path
remains the internal `data` network, while an otherwise empty non-internal `source-access` bridge
permits only the explicitly declared `127.0.0.1` binding. External connectors use the explicit
non-internal `connectors` network plus deployment DNS/firewall policy; they are not attached to the
source-access bridge.

The local Ollama adapter is development-only. Container mode accepts only
`http://host.docker.internal:11434/v1`; explicit source-host development accepts the exact
loopback origin `http://127.0.0.1:11434/v1`. The ignored environment selects the installed model,
bounded context and timeout; source, bootstrap and Admin do not supply a model fallback. It submits
only a fixed non-executable answer/citation function and
validates its output as untrusted evidence. It does not make the model a production provider.
Neo4j is a rebuildable projection sandbox until a future verified release-projection adapter
exists; do not write DataRiver canonical state to it. The full decision and promotion limits are
in [ADR-0023](adr/0023-mac-development-local-inference-and-graph-projection.md).

ADR-0030 adds a separate development-only bridge for an authenticated model server operated on the
private corporate network. It is not an external commercial-provider route: the endpoint must be
HTTPS `/v1`, match the operator's exact host allowlist, resolve only to private non-loopback
addresses and use a mounted API-key secret. Chat, Embedding and Neo4j are configured and proven
independently; a feature route checks only its declared capabilities. Compose mounts each optional
API-key secret only into the process that declares that provider capability: general interactive
routes use the API mounts, while the opt-in PDF worker receives only its Chat and Embedding keys.
Source-host loopback Ollama is accepted only with the explicit development source-host switch, while container mode keeps the
`host.docker.internal:11434` boundary. Production keeps this bridge disabled, and no provider
endpoint, credential or allowlist is browser-controlled.

Reranking is not an OpenAI-compatible surface. The optional private profile uses
`INTRANET_RERANK_V1` and an HTTPS `/v1` base, with a canonical mounted reranker key. Mac development
may instead use `LOCAL_LLAMA_CPP` at the fixed
`http://host.docker.internal:11435/v1` endpoint. Its GGUF is resolved from the Ollama model store and
served by `scripts/local_reranker_service.py`; Ollama itself is not claimed to provide a rerank
route. TEST executes a fixed bounded `POST /v1/rerank`, records `RERANKING_INFERENCE` only after validating ordered finite
scores and shares the probe destination/TLS/redirect/body-size controls. Governed Chat may consume
the deployment-selected reranker after authorization and bounded retrieval; it never expands the
authorized evidence set and a reranker failure makes that selected route unavailable instead of
silently falling back. Ollama itself does not implement this route; the Mac bridge's local
connection evidence is distinct from the WSL/private endpoint gate, which remains external.

Local Chat keeps the configured inventory endpoint at the fixed `/v1` base but sends generation to
the same Ollama origin's native `/api/chat` route. This is intentional: Ollama's OpenAI-compatible
route does not apply `options.num_ctx`, while the native route applies the operator-selected
`LOCAL_OLLAMA_CHAT_CONTEXT_TOKENS` bound. The adapter still owns the fixed route, disables proxy and
redirect handling, bounds the response body and validates the returned tool call as untrusted data.

Exact host allowlisting occurs before DNS and every returned address is checked. The current
default HTTP transport is not address-pinned and may resolve again during connection, so private
deployment acceptance must retain DNS-rebinding as open until the connection uses the vetted
address set while validating TLS against the original hostname.

Set `DATAHUB_BASE_URL` and review origins/ports in `.env`. Optional `UI_DATAHUB_URL`, `UI_AIRFLOW_URL`, `UI_GRAFANA_URL`, `UI_PROMETHEUS_URL`, and `UI_GRAPH_URL` values populate the GNB auxiliary links through the authenticated capabilities response. They are not provider API endpoints or embed authorities: URLs with user information are rejected, missing values create no fallback link, and production requires HTTPS. The production validator rejects wildcard CORS, HTTP external URLs, password-bearing URLs and seed activation. Only `file:` secret references are implemented; a Vault/KMS adapter is a separate deployment integration.

`WORKSPACE_SELECTION_ENABLED=false` selects the server-verified default Workspace and hides manual
switching; it never disables Workspace request scope, ABAC or RLS. The default must exist or the UI
fails closed. `OIDC_HARDWARE_WEBAUTHN_ENABLED=false` removes DataRiver enrollment/step-up entry
points and makes the API verifier refuse `HARDWARE_WEBAUTHN` assurance. It does not enable a
password downgrade, so direct high-risk mutations remain unavailable. These are operator-owned
process settings, not browser-editable administrator records. Recreate the API container after a
change so `/auth/me` and token verification share the same configuration.

Admin System Settings is read-only and test-only. The selected deployment environment and mounted
secret files are the sole live configuration source; the browser cannot save or activate a second
database-backed configuration. Apply environment changes with the matching managed update/restart
workflow and verify each recreated process independently. See
`docs/41_DEPLOYMENT_ENVIRONMENT_CONFIGURATION.md`.

An isolated development network without DNS/TLS may place an exact connector IP in both
`SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS` and
`SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS`. The second list is an explicit transport-risk
acceptance for fixed server-owned probes, not a general HTTP client allowlist; it accepts no
hostname, URL, port, CIDR or wildcard and does not relax inference-gateway or production
browser-link HTTPS requirements (ADR-0067).

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

Workspace administrators may separately save Monitoring Dashboard Links through the versioned
Monitoring tab editor. Fresh administrator assurance approves those credential-free HTTP(S) links
for sandboxed, no-referrer iframe presentation; the edge CSP therefore permits HTTP(S) frame
sources. This does not create a connector or cause the server to fetch the destination. Each frame
keeps a new-window fallback because a target site's own `frame-ancestors` or `X-Frame-Options`
policy may still deny embedding and cannot be overridden by DataRiver.

Static validation and start:

```bash
scripts/compose.sh --env-file .env -f compose.yaml config --quiet
scripts/compose.sh --env-file .env -f compose.yaml up -d --build --wait
```

All local overlays can be validated and started as one model:

```bash
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml config --quiet
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
```

The observability services are an explicit opt-in profile. They bind their three UIs to loopback
only, generate the Grafana bootstrap password in the ignored `secrets/` directory, and do not get
the API's OIDC token or DataHub secret:

```bash
scripts/compose.sh --env-file .env -f compose.yaml -f aux-compose.yml \
  --profile observability config --quiet
scripts/compose.sh --env-file .env -f compose.yaml -f aux-compose.yml \
  --profile observability up -d --wait
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

### WSL intranet source-host ingress

WSL preparation supports a second, explicit development topology for rapid `linux/amd64` source
validation. It is not the `wsl-preparation` immutable release profile. The operator derives a
separate ignored environment with `bootstrap.sh --host-development --intranet-source-host` and
supplies two distinct standard-port HTTPS origins: one for Web and one for Keycloak. Source Uvicorn
and Vite, container PostgreSQL/Keycloak and separately composed Redis remain loopback-only.

Only an operator-managed Nginx TLS edge listens on the LAN. The repository renderer requires the
explicit development flag, exact public origins, certificate/key paths and one or more bounded
client CIDRs. It emits separate virtual hosts, `deny all`, HSTS and loopback proxy targets. It
rejects production, HTTP, same-host origins, symbolic links and all-network CIDRs. The internal CA,
certificate SANs, corporate DNS, Windows/Hyper-V firewall and approved CIDRs remain deployment
inputs and external gates.

In WSL mirrored mode the Hyper-V firewall admits only TCP 443 from approved clients. NAT
`portproxy` is a fallback that loses the original client address; in that shape the Windows Domain
firewall enforces the client CIDR and Nginx accepts only the exact Windows gateway `/32`. No mode
publishes PostgreSQL, Redis, API, Vite or Keycloak upstream ports to the LAN.

Before source processes start, stop the containerized API/web/workers but preserve infrastructure
containers and volumes. `workflow_source_host_infra.py prepare` reads the recorded applied profile
and owns this transition. Build mode retains registry digest pins and builds the local identity
image; offline mode verifies the release override/manifest checksums and loaded image IDs before
using tag references restored by `docker load`. Both resolve the same reviewed logical images and
append `compose.source-host.yaml`, so `docker port` reports `127.0.0.1:5432`; bare `5432/tcp` is
container metadata, not a host listener. The exact recovery, Nginx and Windows commands are in the
root README. The controlling decisions are
[ADR-0051](adr/0051-wsl-intranet-source-host-ingress.md) and
[ADR-0052](adr/0052-deployment-aware-source-host-infrastructure.md).

Optional source-host Neo4j uses the separately derived environment and the selected
`NEO4J_BOLT_PORT`, not the container profile's Docker DNS endpoint. Supplying
`--neo4j-bundle-dir` makes the infrastructure workflow verify the external bundle SHA-256,
manifest schema and matching upstream digest fields, image ID and `linux/amd64` platform before
mutation, then require an authenticated healthcheck and Cypher query. This repository never carries
the image archive. See
[ADR-0053](adr/0053-verified-neo4j-source-host-profile.md).
When the verified archive was transferred separately and already loaded with `docker image load`,
`--reuse-loaded-neo4j` instead verifies the approved local tag and `linux/amd64`, starts with pulls
disabled and performs the same authenticated checks. This development convenience claims no
release acceptance; see
[ADR-0055](adr/0055-preloaded-neo4j-source-validation.md).

A rapid-source host that predates managed applied state supplies an explicit environment file. The
workflow then automatically selects a development-only local-image path, verifies that the
configured PostgreSQL and final Keycloak images exist as `linux/amd64`, and starts them with
`--pull never --no-build`. It writes no release acceptance state. Approved local references may be
selected with `SOURCE_HOST_POSTGRES_IMAGE` and `SOURCE_HOST_KEYCLOAK_IMAGE`.
`--reuse-local-images` forces the same path when an applied state exists; `--connected-build`
remains only as a compatibility alias. This is not an offline deployment fallback; managed offline
and production paths retain digest/release verification.

## Network and identity rules

- Core container defaults remain web `8080`, API `8000` and Keycloak `8081`. Host-development uses Vite `38102`, source API `38101`, Keycloak `18081`, APISIX `9080` and Airflow `8082` when their overlays are enabled.
- PostgreSQL stays on the private `data` network and has no host bind in the core file. Connector-consuming processes also join `connectors`; Redis/S3/DataHub ingress remains owned and firewalled by those deployments.
- API has an RLS-constrained database role; migration owns DDL. Relay, upload, governance and bootstrap have distinct least-privilege database identities and service-specific secret mounts. Airflow and Keycloak have distinct databases/roles.
- APISIX standalone mode has no administration/control port and does not replace application ABAC.
- APISIX and web run non-root with read-only root filesystems. APISIX renders configuration and request temp files only into bounded, non-executable tmpfs; its health check executes a real proxied HTTP request rather than trusting a process-only command. Its declarative upstream uses APISIX DNS discovery through Docker's embedded resolver, so replacement of the API container does not pin a stale startup address.
- Web Nginx uses Docker's embedded DNS resolver for the API upstream. API container replacement therefore does not require web restart and must be included in recovery acceptance.
- Web Nginx `1.30.3` uses recursive `add_header_inherit merge` so the canonical CSP, nosniff,
  no-referrer, frame-denial and Permissions Policy headers survive every cache-defining location and
  every response status. The API proxy replaces upstream copies of only those fields; upstream
  cache/auth/retry/ETag/download/request-ID fields pass through. Run the native-image matrix below
  after every template, base-image or edge change:

  ```bash
  docker build --pull=false -f frontend/Dockerfile -t datariver-next-web:header-gate .
  uv run python scripts/verify_nginx_headers.py --web-image datariver-next-web:header-gate
  ```

  The verifier uses `--pull=never`, rejects daemon/image architecture mismatch and creates only an
  internal temporary network. Run it separately on Mac arm64 and preparation-PC WSL amd64. It tests
  empty and populated envsubst rendering, a real hashed asset, SPA/runtime/health routes, API
  success/error, missing asset, conditional `304` and a removed-upstream `502/504`.
- Production exposes only a TLS edge. Direct local API/identity ports must be removed or firewalled by the environment override.
- The production HTTPS edge must preserve or intentionally strengthen these headers on every status,
  emit exactly one approved HSTS value on HTTPS and never serve application content over plain
  HTTP. Inner-container HTTP evidence does not satisfy this external acceptance gate.

## Worker correctness

- PostgreSQL outbox is canonical. Relay publishes IDs to the external Redis delivery stream; failed events are individually retried, dead-lettered after the configured maximum and exposed in operations. Published outbox and completed inbox rows are not automatically pruned until the governed WORM/Legal-Hold/Maker-Checker retention gate is implemented and accepted.
- External Redis cache has bounded volatile memory and an evicting policy; Redis delivery is separate, `noeviction`, with deployment-reviewed persistence/recovery. They never share a URL/database or credential.
- Upload completion reconciles an already-completed multipart operation via object `HEAD`. Validation streams chunks and promotes with copy-before-manifest-commit; a stale quarantine duplicate is safe to clean later.
- Governance application uses a PostgreSQL job/attempt lease. Transient DataHub failures back off automatically; terminal/mismatched content reaches `APPLY_FAILED` and requires authorized requeue.
- Catalog export is disabled by default. Enable the `catalog-export` Compose profile only after
  bootstrap creates its independent credentials with `-EnableCatalogExportWorker`. It uses an
  independent NOBYPASSRLS database principal and independent non-admin S3 identity, enumerates only
  workspace identifiers before
  setting transaction-local workspace context, and receives no DataHub credential or egress. Each
  attempt uses a distinct object key; only the current unexpired lease can publish its receipt.
- Durable Knowledge source analysis is disabled by default. Bootstrap creates
  `postgres_knowledge_password` and `s3_knowledge_{access_key,secret_key}` separately from the API,
  owner, upload, export and archive identities; `--enable-knowledge-source-worker` on Unix/WSL or
  `-EnableKnowledgeSourceWorker` on PowerShell sets their references only after one complete Chat +
  Embedding pair is configured. The worker role is `NOBYPASSRLS`, receives no migration/DDL
  authority, and its S3 principal requires only `GetBucketLocation` plus `GetObject` in the exact
  accepted bucket. It does not receive a DataHub token or Neo4j credential.

  On a local MinIO reference deployment, first run `storage-init` so every configured bucket
  exists, then run `minio-knowledge-identity-init` from `compose.local-connectors.yaml`. The latter
  renders `infra/minio/knowledge-read-policy.template.json` with the configured
  `S3_BUCKET_ACCEPTED`, creates the generated non-admin user and attaches that read-only policy.
  An external S3/MinIO owner must perform the equivalent bucket/IAM work and record positive
  accepted-object reads plus anonymous, write, delete and other-bucket negatives. That evidence is
  an `EXTERNAL_GATE`; the local initialization is not evidence for the external target.

  The API stores a pinned immutable-source/base/ontology/provider decision without calling an
  external provider. The worker claims it with a database-clock lease, hash-only random token,
  epoch and immutable attempt. It renews/checks the lease between bounded batches. A queued or
  retry-wait cancellation is terminal immediately; a running cancellation becomes
  `CANCEL_REQUESTED` and is linearized by the fenced final transaction. An expired attempt becomes
  `SUPERSEDED`; the worker either requeues within the stored maximum-attempt limit or reaches a
  terminal state. Operators must never edit job, attempt, lease, event or DRAFT rows.

  Each source is capped at 50 MiB and 500 pages. Only
  `KNOWLEDGE_SOURCE_MEMORY_SPOOL_BYTES` (default 1 MiB) is retained in memory; larger input spills
  to the worker-only `knowledge-spool` volume at the absolute non-root
  `KNOWLEDGE_SOURCE_SPOOL_DIRECTORY`. The directory must be writable by the worker and inaccessible
  to API/web processes. Capacity must cover one 50-MiB source per concurrent worker plus temporary
  and provider overhead; monitor volume free space and never treat spool bytes as durable evidence.

  Emergency disablement sets `KNOWLEDGE_SOURCE_WORKER_ENABLED=false`, recreates the API so enqueue
  fails closed, and stops `knowledge-source-worker`. It does not delete queued or terminal
  evidence. Authorized users cancel through the version-fenced API/UI; on a later restart, the
  worker safely reclaims an expired lease or completes the pending cancellation.
- Retention archive execution is disabled by default and is not part of core startup. The
  `retention-archive` profile creates a scheduler with only its dedicated PostgreSQL secret and a
  separate archive worker with a different PostgreSQL secret plus dedicated immutable-store
  credentials. Both use pool size 1/overflow 0, concurrency 1 and an explicit workspace allowlist.
  The scheduler has no S3 credential. Set `RETENTION_ARCHIVE_EXECUTION_ENABLED=true` only after all
  `S3_ARCHIVE_*` values, lower-case SHA-256 encryption/principal fingerprints and separate secret
  files are accepted. This flag is necessary but not sufficient: both workers also reread
  `RETENTION_EXECUTION_CONTROL_FILE`, which bootstrap creates as `DISABLED`. Start the processes
  disabled, complete provider/restore/owner acceptance, then atomically replace the file with the
  exact single line `ENABLED`:

  ```bash
  scripts/compose.sh --env-file .env --profile retention-archive config --quiet
  scripts/compose.sh --env-file .env --profile retention-archive up -d --build \
    retention-scheduler retention-archive-worker
  umask 077
  printf 'ENABLED\n' > runtime/retention-execution.enabled.tmp
  mv runtime/retention-execution.enabled.tmp runtime/retention-execution.enabled
  ```

  Disable immediately by atomically replacing the same file with `DISABLED`; do not edit it in
  place. Archive evidence uses a command-deterministic key and a precommitted capability-attestation
  UUID in object metadata. The adapter probes before a write, creates with `If-None-Match: *` and no
  SDK automatic retry, then probes again after an ambiguous response. A disable, governance change or DB
  completion failure observed after full WORM verification blocks the job and records the exact
  immutable receipt as reconcilable evidence. Every expired write lease first receives a read-only
  recovery fence; a cold process loads the exact attestation using provider `LastModified`. Its
  whole-second timestamp is treated as `[t, t+1s)`, and both the policy and exact capability must
  cover that entire interval. For V2 this includes the contract effective interval and the execution
  authorisation deadline. The recovery process
  cannot run the capability probe or create another object. Transient reads have three persistent
  fences per write attempt and never expand the stored write-attempt budget.
  Provider checksum/retention mismatch remains fail-closed and must be reconciled by the operator
  against the deterministic key. None of these paths authorizes deletion.

  Each worker exposes a bounded Prometheus endpoint on container port
  `RETENTION_METRICS_PORT` (default `9102`) without a host publication. A reviewed Prometheus
  deployment must join an allowed internal scrape network; never publish this endpoint broadly.
  Labels are limited to fixed worker/outcome vocabularies. The profile archives only a one-MiB-or-
  smaller pseudonymised erasure-evidence manifest and always leaves deletion/partition operations
  `DISABLED_NOT_READY`. Before activation, the real target must prove versioning, Object Lock
  COMPLIANCE, full SHA-256 read-back, exact retention read-back, shortening denial, retained-version
  delete denial and an off-host restore. Source/unit tests or an S3 product label do not close this
  target gate.

  `S3_ARCHIVE_WORKER_PRINCIPAL_FINGERPRINT` is audit attribution supplied by deployment
  configuration, not provider-discovered caller identity. Before activating a real target, the
  accountable operator must record evidence that this SHA-256 value identifies the exact access-key
  principal mounted into the archive worker; a configured value alone is insufficient. HA scale-out
  must also rehearse concurrent same-workspace capability probes against the target because cached
  observations share a configuration/time uniqueness boundary.

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

For source-host development, `bootstrap.sh --host-development` persists a deployment-owned Airflow
API origin in ignored `.env`. macOS and Windows-host source use `host.docker.internal:38101`. When
the source API itself runs on Linux/WSL, the operator explicitly adds
`--source-host-airflow-bridge`; it selects `host.docker.internal:38103` and `dev_host.sh` starts a
standard-library bridge only on Docker's validated private default-bridge gateway. It forwards
solely to the still-loopback-only source API.
Airflow otherwise defaults to the container topology's `http://api:8000`; that name is deliberately
absent when API and workers run from a checkout, so every task would fail before reaching DataHub.
Recreate all four Airflow services after changing this value. Its `NO_PROXY`/`no_proxy` list
explicitly covers only local Compose and source-host names, preventing a workstation proxy from
intercepting Keycloak client-credentials or internal API calls. It does not grant Airflow DataHub
egress or a DataHub credential. The complete Linux/WSL boundary is
[ADR-0032](adr/0032-linux-source-host-airflow-loopback-bridge.md).

## Database and object operations

- Alembic has one head at `0066`: the generated current initial schema plus conditional
  compatibility bridges for local databases that applied earlier revisions. Deployment runs
  migration before API/workers. The API role can only read `public.alembic_version` for readiness;
  migration ownership remains separate. After explicitly bounded compatibility repairs, the Policy
  Book and retention-execution bridges verify exact column type/length/nullability/timezone/default,
  PK/UQ, CHECK SQL, FK columns/target/delete action, index columns/uniqueness and forced-RLS policy
  definitions; same-name malformed objects and every remaining partial schema are rejected.
  Revision `0044` adds the bounded Admin cursor indexes concurrently and outside a migration
  transaction. Revision `0045` bounds the rebuildable catalog projection to ADR-0039 limits.
  Revision `0046` adds database-time registration leases, append-only Manual attempt/aspect
  evidence, retry schedules, typed-BULK binding uniqueness and bounded CR indexes. Its re-entry
  guard validates the complete evidence column, constraint, RLS, trigger, grant and index contract
  and fails closed on nullability, FK or same-name index drift. Stop registration workers and
  resolve every Manual `QUEUED` or `APPLYING` row before an additive `0045 -> 0046` upgrade.
  Revision `0054` adds the durable Knowledge source job/attempt/event ledger, the DRAFT and
  extraction bindings, FORCE-RLS policies, fenced triggers and worker discovery/finalization
  functions. It refuses to run unless `datariver_knowledge` is an unprivileged NOBYPASSRLS LOGIN
  with no role membership that could permit `SET ROLE`. It removes prior direct privileges across
  application schemas before applying the exact worker allowlist; canonical evidence DELETE
  triggers provide a second fail-closed boundary against later grant drift.
  Its downgrade refuses to erase the schema after any durable source-analysis job exists; preserve
  the database and apply a forward fix rather than deleting audit evidence.
  Revision `0055` adds atomic API-product ledger/result/month usage, subject-bound consumer grants
  and fixed prepare/complete functions. Canonical and additive paths verify the exact columns,
  constraints, indexes, FORCE-RLS policies, triggers, function attributes and grants; same-name
  malformed objects fail migration. Downgrade refuses while V2 grants or evidence exist.
  Revisions `0059` and `0060` add author-scoped Studio Draft/T-Box and normalized A-Box mapping
  contracts. Revision `0061` adds exact pre-flight receipts, immutable Studio schema/mapping
  Releases and restrictive maker-checker publication policies without changing instance Releases
  or Neo4j. Revision `0062` adds deterministic workspace DOMAIN seed data and auditable,
  non-destructive Knowledge graph archival. Revision `0063` adds the typed ontology-builder block,
  proposal and durable ingestion ledgers. Revision `0064` normalizes Draft Class hierarchy,
  Property ownership and Relationship endpoints under forced RLS. Revision `0065` adds named
  Unicode-safe hierarchy semantics and the covering parent/child lookup index. Revision `0066`
  adds Studio endpoint-alias arrays, managed-domain provenance/version and document Proposal source
  references.
- Existing PostgreSQL volumes must reconcile runtime roles before migration so `0042`, `0054` and `0055`
  can grant their least-privilege capabilities. Bootstrap first so the new Knowledge password file
  exists, start PostgreSQL, run `DATARIVER_ENV_FILE=<file>
  scripts/reconcile-postgres-roles.sh` on macOS/Linux/WSL or
  `scripts/reconcile-postgres-roles.ps1 -EnvFile <file>` on Windows, run the migration service, then
  run the same reconciliation once more. The second pass is intentional: the idempotent init hook
  reasserts passwords/role attributes and its conditional compatibility grants after an old volume
  has crossed the relevant revisions; `0054` itself owns the Knowledge worker grants. Never stamp
  past a missing role or grant the worker BYPASSRLS.
- PostgreSQL pool size/overflow/lease timeout, statement timeout, idle-transaction timeout and application names are explicit. Budget `API replicas × (API pool + overflow) + long-running workers × (worker pool + overflow) + one-shot/IdP/Airflow/admin reserve`; current one-API/four-worker defaults have a ceiling of 60 before reserve.
- Liveness is process-only. Readiness leases the API pool and requires exactly packaged Alembic
  head `0066`; Compose and APISIX use readiness for upstream health.
- `scripts/probe_pgbouncer_rls.py` and its unit contract implement the pre-adoption transaction-pool leakage gate. No Compose profile currently deploys PgBouncer and no live pooler pass has been recorded; direct PostgreSQL remains the supported path until the isolated two-workspace probe succeeds.
- Back up PostgreSQL and the selected external S3 store as a consistency set or record a watermark; restore into isolation and follow the drill in [operations runbook](13_OPERATIONS_RUNBOOK.md) before traffic.
- Accepted-object retention/lifecycle is environment policy. Quarantine receives a shorter cleanup policy, but never delete an object whose manifest is actively leased.
- Initial recovery targets (RPO <= 5 minutes, RTO <= 60 minutes) are objectives until an environment drill records measured evidence.

The general Chat assistant provider is not a promoted production runtime component. The
development-only exceptions in ADR-0023 and ADR-0030 use fixed non-executable contracts. Compose
now has one opt-in durable queue/worker specifically for PDF-to-DRAFT Knowledge source analysis;
it is not a general Chat queue and cannot publish a release or mutate DataHub. Production Chat
provider integration, Chat dispatch/SSE, pre/post-call live policy/profile revalidation and scaled
operational/red-team evidence remain promotion gates.

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

`application.ports.ObjectStore` is the provider-neutral S3 boundary and
`infrastructure.object_store.S3ObjectStore` uses only that contract. A separately operated
MinIO-compatible endpoint can therefore be selected without changing use cases; no MinIO image,
administrator credential, lifecycle or data volume is bundled. Existing SeaweedFS bytes require an
explicit inventory/copy/checksum/read-back/cutover procedure rather than an endpoint edit. Immutable
archive promotion uses the separate port and evidence gate in ADR-0012/ADR-0033; no provider label
or Object Lock setting is treated as WORM acceptance.

## Failure behavior

| Failure | Expected behavior |
|---|---|
| DataHub | local authorized search/monitoring remain; enrichment/apply/sync degrade; no false `APPLIED` |
| Redis cache | higher latency only |
| Redis delivery | outbox accumulates; relay later recovers delivery |
| object store | upload unavailable; catalog/change/KG remain |
| Airflow | scheduled sync/probe delayed; interactive paths remain |
| Knowledge source worker or Chat/Embedding provider | new analysis enqueue is disabled when capability is not ready; core catalog/governance and existing Knowledge reads remain |
| Keycloak/OIDC | protected requests fail authentication; public liveness remains |
| optional gateway | core loopback API remains available only where deployment policy allows |
