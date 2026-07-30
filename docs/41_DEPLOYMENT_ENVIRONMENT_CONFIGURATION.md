# Deployment environment configuration

DataRiver has one live configuration source: the environment selected by the deployment operator,
plus mounted secret files. Admin **System settings** is a read-only projection of the validated
settings already loaded by the API process. It cannot read a host `.env` file, write one, save a
second desired state in PostgreSQL, or hot-reload a process.

## Select one environment

Fresh setup requires an explicit topology profile and creates an ignored environment file for that
profile:

```bash
./scripts/workflow_fresh_setup.py \
  --profile portable-development \
  --datahub-mode external \
  --redis-mode local \
  --storage-mode local \
  --airflow-mode skip
```

The default path is `.env.<profile>`. `--env-file /reviewed/path/to/name.env` selects a different
path. The workflow records that exact path in
`runtime/operator-workflow/<profile>.json`; both Compose interpolation and container `env_file`
receive it. No host OS is auto-detected.

| Profile | Purpose | Runtime artifacts | Default external boundary |
|---|---|---|---|
| `portable-development` | General Linux development on arm64 or amd64 | Build from source | DataHub |
| `mac-development` | Reviewed Apple-Silicon local compatibility topology | Build from source | None |
| `wsl-preparation` | Reviewed amd64 offline runtime | Verified release archive | DataHub, storage, Airflow |

`wsl-preparation` remains the immutable image/release profile. A preparation PC that also performs
rapid source validation derives a separate ignored `.env.wsl-intranet-development` with
`bootstrap.sh --host-development --intranet-source-host` and two operator-selected HTTPS origins.
That explicit development mode keeps all upstream ports loopback-only and publishes only the
CIDR-restricted Nginx TLS edge defined by
[ADR-0051](adr/0051-wsl-intranet-source-host-ingress.md). It is not a fourth managed release
profile, is not production, and does not alter the workflow state for `wsl-preparation`.
`workflow_source_host_infra.py` consumes that existing state to hide build-versus-offline Compose
selection, while an explicitly supplied intranet environment supplies only the runtime origins and
ports. It never turns an arbitrary tag into accepted release evidence.
A pre-state rapid-source host with an explicit environment automatically selects registry-disabled
local-image reuse. The workflow verifies configured PostgreSQL and Keycloak images as
`linux/amd64`, uses `--pull never --no-build`, and writes no applied or release state.
`--reuse-local-images` forces this behavior when a state exists; `--connected-build` is retained as
a compatibility alias. This development exception does not weaken managed offline or production
digest verification.

To apply an edited environment:

```bash
./scripts/workflow_update_restart.py --profile portable-development
```

Use the same profile selected during fresh setup. `--env-file` may be supplied only when
deliberately switching the state to another reviewed environment file. The workflow stores
per-key SHA-256 fingerprints, never values, and recreates the API, web, workers or optional local
connector processes that consume changed keys. The applied-state file is permission-restricted.

## Copy/paste contract

`.env.example` is the exhaustive committed option catalog. Copy it to the selected ignored file;
never commit the result. Admin provides a smaller copy button for the keys relevant to one system.
Those templates contain key names with blank values, not model names, hosts or credentials.

Values below in angle brackets are operator choices, not product defaults:

```dotenv
APP_ENV=development
APP_PUBLIC_ORIGIN=<browser-origin>
APP_CORS_ORIGINS=<comma-separated-browser-origins>
APP_TRUSTED_HOSTS=<comma-separated-hosts>

DATAHUB_BASE_URL=<gms-origin>
DATAHUB_SECRET_REF=file:/run/secrets/datahub_token

# Exact immutable version already approved in the active classification-access
# policy. This is a UUID, not a model name or endpoint.
CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID=<approved-chat-profile-version-uuid>
CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID=<approved-embedding-profile-version-uuid>
CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID=<approved-reranker-profile-version-uuid>

LOCAL_INFERENCE_ALLOWED_HOSTS=<comma-separated-runtime-reachable-hosts>
LOCAL_OLLAMA_CHAT_ENABLED=false
LOCAL_OLLAMA_CHAT_BASE_URL=<ollama-origin-ending-in-/v1>
LOCAL_OLLAMA_CHAT_MODEL=<installed-model-id>

LOCAL_OLLAMA_EMBEDDING_ENABLED=false
LOCAL_OLLAMA_EMBEDDING_BASE_URL=<openai-compatible-origin>
LOCAL_OLLAMA_EMBEDDING_MODEL=<installed-model-id>

LOCAL_LLAMA_CPP_RERANKER_ENABLED=false
LOCAL_LLAMA_CPP_RERANKER_BASE_URL=<rerank-v1-origin>
LOCAL_LLAMA_CPP_RERANKER_MODEL=<installed-model-id>

INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS=<private-gateway-host>
INTRANET_OPENAI_COMPATIBLE_APPROVED_PUBLIC_HOSTS=<optional-approved-public-gateway-host>
INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED=false
INTRANET_OPENAI_COMPATIBLE_CHAT_BASE_URL=<https-gateway-prefix-ending-in-/v1>
INTRANET_OPENAI_COMPATIBLE_CHAT_MODEL=<approved-model-id>
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED=false
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_BASE_URL=<https-gateway-prefix-ending-in-/v1>
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_MODEL=<approved-model-id>
INTRANET_RERANKER_ENABLED=false
INTRANET_RERANKER_BASE_URL=<https-gateway-prefix-before-/rerank>
INTRANET_RERANKER_MODEL=<approved-model-id>
```

An unset optional field and an explicitly disabled adapter are both unconfigured. Enabling an
adapter without every required endpoint/model/reference fails Settings validation; there is no
source-code fallback.

For the Mac-only loopback Reranker, the selected fresh/update workflow owns the managed process
lifecycle. An enabled supported profile starts or reuses only the PID whose command, model blob and
fixed `127.0.0.1:11435` port match the recorded state. Disabling the adapter or applying a profile
that does not support the local Reranker stops only that verified owned process. Operators may
inspect or reconcile it directly without supplying an endpoint:

```bash
.venv/bin/python scripts/local_reranker_service.py status \
  --model <installed-reranker-model-id>
.venv/bin/python scripts/local_reranker_service.py probe \
  --model <installed-reranker-model-id>
.venv/bin/python scripts/local_reranker_service.py start \
  --model <installed-reranker-model-id>
.venv/bin/python scripts/local_reranker_service.py stop
```

`stop` refuses to signal a recorded PID whose command is not the managed loopback `llama-server`.
Portable and WSL profiles never start this Mac-only bridge.

## Option groups

### Application and browser

- `APP_ENV`, `APP_NAME`, `APP_LOG_LEVEL`, `APP_PUBLIC_ORIGIN`, `APP_CORS_ORIGINS`,
  `APP_TRUSTED_HOSTS`, `INTRANET_SOURCE_HOST_ENABLED`, `DEPLOYMENT_TIER`, `API_PORT`, `WEB_PORT`
- `UI_DATAHUB_URL`, `UI_AIRFLOW_URL`, `UI_GRAFANA_URL`, `UI_PROMETHEUS_URL`,
  `UI_GRAPH_URL`
- `WORKSPACE_SELECTION_ENABLED` defaults to false and hides manual selection while retaining the
  server-selected Workspace, ABAC and RLS request scope. Enable it only for a reviewed
  multi-Workspace deployment whose users must switch memberships.

### PostgreSQL

- Runtime roles: `DATABASE_*`, `RELAY_DATABASE_*`, `UPLOAD_DATABASE_*`,
  `GOVERNANCE_DATABASE_*`, `KNOWLEDGE_DATABASE_*`, `EXPORT_DATABASE_*`,
  `RETENTION_SCHEDULER_DATABASE_*`, `ARCHIVE_DATABASE_*`
- Operator roles: `MIGRATION_DATABASE_*`, `BOOTSTRAP_DATABASE_*`
- Pool/readiness: `DATABASE_POOL_*`, `WORKER_DATABASE_POOL_*`,
  `DATABASE_READINESS_TIMEOUT_SECONDS`

Database URLs contain a role and endpoint but no password. Each `*_SECRET_REF` points to a mounted
file. Bootstrap generates the reviewed local role layout; external deployments must provide
equivalent least-privilege roles.

### Identity and administrator assurance

- `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, `OIDC_PUBLIC_AUTHORITY`,
  `OIDC_PUBLIC_ORIGIN`, `OIDC_CLIENT_ID`
- `OIDC_HARDWARE_WEBAUTHN_ENABLED` defaults false. Turning it on requires a matching IdP flow.
  Turning it off does not downgrade hardware-gated mutations to password-only authorization.
- `IDENTITY_ADMIN_*` enables the bounded IdP provisioning adapter only when its dedicated
  service-account secret reference is mounted.
- `ADMIN_PASSWORD_FALLBACK_*` is a separately governed recovery workflow, not a WebAuthn bypass.
- `DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED` defaults false and is accepted only with
  `APP_ENV=development`, the governed password-fallback switch enabled and hardware WebAuthn
  disabled. It is a visible, fresh-password `admin.manage` test exception; it never asserts
  WebAuthn or overrides a non-authentication ABAC denial.

### Catalog and workflow systems

- DataHub: `DATAHUB_BASE_URL`, `DATAHUB_SECRET_REF`, `DATAHUB_EXPECTED_VERSION`,
  `DATAHUB_ALLOWED_VERSIONS`, `DATAHUB_VERSION_ENFORCEMENT`, timeout/concurrency/circuit keys,
  and PIT evidence keys
- Disabled-by-default one-target Profile collector: `CATALOG_PROFILE_COLLECTOR_ENABLED`,
  `CATALOG_PROFILE_DATABASE_URL`, `CATALOG_PROFILE_DATABASE_SECRET_REF`,
  `CATALOG_PROFILE_DATAHUB_SECRET_REF`, `CATALOG_PROFILE_SUBJECT_ID`,
  `CATALOG_PROFILE_FRESHNESS_SLA_SECONDS`, `CATALOG_PROFILE_PROVIDER_CONFIG_HASH`,
  `CATALOG_PROFILE_PROVENANCE_KEY_ID` and
  `CATALOG_PROFILE_PROVENANCE_KEY_SECRET_REF`. Enabling requires all values, an enforced
  DataHub release pin and three distinct file-mounted credentials.
- Disabled-by-default GX execution plane: `QUALITY_WORKER_ENABLED`, `QUALITY_DATABASE_URL`,
  `QUALITY_DATABASE_SECRET_REF`, `QUALITY_WORKER_SUBJECT_ID`, `QUALITY_WORKER_WORKSPACE_ID`,
  `QUALITY_SOURCE_MANIFEST_FILE`, `QUALITY_SOURCE_SECRET_ROOT`, `QUALITY_WORKER_FINGERPRINT`,
  `QUALITY_WORKER_LEASE_SECONDS`, `QUALITY_DISPATCH_MAX_DUE_SCHEDULES` and
  `QUALITY_DISPATCH_MAX_CREATED_RUNS`. The update workflow may recreate an already-running
  worker, but never enables the explicit `quality-execution` Compose profile.
- Redis: separate `REDIS_CACHE_*` and `REDIS_DELIVERY_*` endpoints and secret references; they
  must not share the same endpoint/policy
- Storage: `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET_*`,
  role-specific `S3_*_KEY_FILE`, CORS mode and presigned TTL
- Airflow is an optional external/bundled orchestrator; `UI_AIRFLOW_URL` is a browser link, not a
  credential-bearing API pass-through.

### Inference and knowledge

- Local Chat: `LOCAL_OLLAMA_CHAT_*`
- Local Embedding: `LOCAL_OLLAMA_EMBEDDING_*`
- Local reranking bridge: `LOCAL_LLAMA_CPP_RERANKER_*`
- Local endpoint hosts: `LOCAL_INFERENCE_ALLOWED_HOSTS`. The list is evaluated by the API
  runtime, so a containerized WSL deployment uses the DNS name or private address reachable from
  that container, while a source-host launcher adds loopback. Changing hosts, URLs or model IDs
  requires the normal process-recreation and governance-binding workflow, never a code edit.
- Private OpenAI-compatible Chat/Embedding:
  `INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS` and the corresponding
  `INTRANET_OPENAI_COMPATIBLE_CHAT_*` / `...EMBEDDING_*` keys
- The private-address-only default may be extended for a company-approved enterprise gateway by
  placing its exact hostname in `INTRANET_OPENAI_COMPATIBLE_APPROVED_PUBLIC_HOSTS`. That list must
  be a subset of the main host allowlist. It accepts neither URLs nor wildcards and does not permit
  loopback, link-local, multicast, unspecified or reserved address ranges.
- Private runtime Reranker: `INTRANET_RERANKER_*`. DataRiver appends the fixed `/rerank`
  route and accepts only a safe HTTPS gateway prefix on the same private host allowlist.
- A provider model ID may be path-like (for example `/models/embedding/bge-m3`). Chat and
  Embedding base URLs may include a gateway prefix but must end in `/v1`.
- A provider inventory URL ending in `/v1/models` is not the base URL: remove only the final
  `/models`. `INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS` contains hostnames/IPs only, never URLs.
- If all three stages share one provider token, copy the same value into the three canonical
  ignored secret files. Do not put it in an environment value. `stream` remains fixed to `false`.
- `SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS` must contain the exact hostname of each configured
  non-inference external connector that an administrator will test, including external DataHub,
  MinIO/S3, Airflow, Prometheus and Grafana endpoints. Inference probes additionally inherit the
  exact `LOCAL_INFERENCE_ALLOWED_HOSTS` and
  `INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS` values; URL schemes, ports, paths and wildcards never
  belong in any host allowlist.
- A DNS-less isolated development network may additionally put an exact connector IP in
  `SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS` when the provider exposes only HTTP,
  `redis://` or `bolt://`. Every value must also be in
  `SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS`. The setting accepts only exact IP literals—never a
  hostname, URL, port, CIDR or wildcard—and one IP covers every fixed probe port at that address.
  It does not relax HTTPS-only intranet inference or production browser-link validation.
- Graph projection: optional offline `NEO4J_IMAGE` override, `NEO4J_PROJECTION_ENABLED`,
  launcher-owned `NEO4J_SOURCE_HOST_ENABLED`, `NEO4J_URI`, `NEO4J_ALLOWED_HOSTS`,
  `NEO4J_DATABASE`, `NEO4J_AUTH_SECRET_REF`, loopback publication ports and bounded
  pool/timeouts. A WSL source-host API uses
  `bolt://127.0.0.1:${NEO4J_BOLT_PORT}`; a containerized API uses `bolt://neo4j:7687`.
- `KNOWLEDGE_PIPELINE_*` and `KNOWLEDGE_SOURCE_*` remain opt-in and fail closed until all required
  deployment adapters and dedicated storage/database roles validate.

Model IDs are always supplied in the ignored environment. The source never selects, pulls,
creates, aliases or falls back to a model. Fixed local ports and host allowlists are transport
security boundaries, not model choices.

`CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID`,
`CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID` and
`CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID` are separate deployment-to-governance bindings. Admin
connection tests may inventory and probe an enabled adapter without them, but an interactive Chat
request may send evidence to a stage only when the current governed classification rule references
that stage's exact approved provider-profile version. The profile's route, provider, model and
deployment identity must also exactly match the effective runtime binding displayed by Admin.
A missing, revoked or mismatched profile produces an explicit unavailable/refused Chat state. It
never falls back to a different model or writes a UUID into source code. The interactive request
budget key binds the workspace, subject and complete classification policy identity
(`policy UUID/version/authorization generation/hash`), so a new policy cannot inherit a previous
policy's consumption bucket.

Admin displays each configured model's effective `options.governance_binding`, including the
server route key, provider identity, environment-selected model identity and a SHA-256 deployment
identity derived from the actual bounded endpoint/contract options. Create and independently
approve one immutable inference provider profile for each enabled stage using those exact values.
Then reference the Composition profile and any enabled Embedding/Reranker profiles in each allowed
classification rule, and place the resulting three version UUIDs in the selected environment. Do
not copy a single profile UUID across stages: the route and model identities are deliberately
different. Connection probes work without these UUIDs, but governed evidence egress does not.

For an isolated development profile with two local human administrators, initialize the exact
three profiles plus active classification/retention contracts explicitly after the runtime
adapters have passed their real probes:

```bash
./scripts/bootstrap_local_governed_chat.py \
  --env-file .env.<selected-development-profile> \
  --maximum-classification <PUBLIC|INTERNAL|CONFIDENTIAL> \
  --jurisdiction <approved-local-jurisdiction> \
  --region <approved-local-region> \
  --attestation-evidence-reference <actual-probe-evidence-reference> \
  --attestation-valid-days <1-365> \
  --restricted-search-grant-maximum-days <1-365> \
  --completed-operation-days <1-3650> \
  --chat-content-days <1-3650> \
  --audit-online-months <1-120> \
  --immutable-archive-years <1-100>
```

The command uses the currently selected model/endpoint/adapter identities; none of those values is
an argument or a source default. For `source-host-development` and `wsl-source-host` it runs through
`dev_host.sh` so the module receives the same loopback translations and ignored secret paths as the
running API; Compose profiles continue to execute inside the API container. It refuses incomplete
stages. When its exact local-development
classification rules differ from the active policy, it creates and independently approves a new
immutable policy version and atomically supersedes the previous one; the selected maximum controls
which classifications from `PUBLIC` through that ceiling can use Chat. On success it writes only
the returned three profile UUIDs and
`CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED=false` to the selected ignored environment.
Apply them with the normal update/restart workflow. The four retention values are local
development acceptance inputs, not a production retention approval.

The Admin fixed connection tests and governed Chat readiness are separate gates. Chat, Embedding
and Reranker must each return `AVAILABLE` from their typed inference probe before their evidence
reference is approved. A successful transport probe does not create governance automatically:
one administrator proposes the stage-specific provider profiles, classification policy and
retention policy, and a different eligible administrator approves them. Until a retention policy
is `ACTIVE`, Chat returns HTTP `409` with
`An active retention policy is required to persist Chat content.` by design. This is neither a
Redis/cache failure nor a reason to edit retention rows directly.

For the checked-in local `test` knowledge graph only, an operator can materialize a bounded
synthetic INTERNAL release and its verified Neo4j shadow projection after the development stack is
healthy:

```bash
docker compose --project-name datariver-next --env-file .env.mac-development exec api \
  /app/.venv/bin/python -m datariver.local_graphrag_fixture
```

The command is rejected outside `APP_ENV=development`, requires the existing two distinct local
human actors, uses the normal typed changeset validation and independent-review state machine,
publishes immutable PostgreSQL release lineage, verifies the Neo4j read-back hash and activates only
that release. It is idempotent after a verified activation. It does not update an arbitrary graph
status, relax the GraphRAG INTERNAL ceiling or create a production data path.

### Retention and observability

- Retention execution remains separately gated by its control file, workspace allowlist,
  immutable archive target and accepted evidence. Environment configuration alone cannot permit
  deletion.
- Prometheus/Grafana URLs are optional links. Embed origins and evidence keys remain distinct from
  provider endpoints.

## Exact connector option index

The following is the complete connector/system option index exposed by Admin templates. A key with
an uncommented value in `.env.example` has the documented development sample/default shown there.
A commented key is optional unless enabling its capability makes it required. Pydantic `Settings`
is the executable required/range/combination contract; startup fails instead of supplying a hidden
endpoint or model.

| Template | Required rule | Runtime consumer and application |
|---|---|---|
| PostgreSQL | `DATABASE_*`, migration/bootstrap and every enabled worker role pair are required | API/workers; role/database bootstrap keys are fresh-setup-only |
| OIDC Identity | issuer, audience and JWKS are required; optional admin/WebAuthn features require their complete sub-group | API/web/Keycloak; public-origin changes also reapply Keycloak |
| DataHub GMS | base URL, token reference and expected version are required | API/catalog workers |
| DataHub Frontend | optional | API/web |
| Airflow | optional UI/workspace integration | API and selected local Airflow |
| Redis Cache/Delivery | both endpoints and independent secret references are required | API/workers; local port/image keys recreate only Redis connectors |
| S3 Storage | endpoint, region, core buckets and core key files are required | API/storage workers; public origin also recreates web |
| Chat | every enabled local/private mode requires its URL and operator-selected model | API |
| Embedding | every enabled local/private mode requires its URL and operator-selected model | API and Knowledge worker |
| Reranker | enabled local bridge requires URL and operator-selected model | API inventory/probe; bridge lifecycle remains operator-owned |
| Neo4j/Knowledge | projection and worker options are optional but complete adapter tuples are required when enabled | API/Knowledge worker; local graph port/image keys recreate Neo4j |
| Prometheus/Grafana | optional links/embeds | API/web |

Platform runtime:

```text
APP_ENV
APP_NAME
APP_LOG_LEVEL
APP_PUBLIC_ORIGIN
APP_CORS_ORIGINS
APP_TRUSTED_HOSTS
DEPLOYMENT_TIER
DEPLOYMENT_EVIDENCE_REFERENCE
SEED_PROFILE
```

PostgreSQL:

```text
POSTGRES_DB
POSTGRES_USER
DATABASE_URL
DATABASE_SECRET_REF
MIGRATION_DATABASE_URL
MIGRATION_DATABASE_SECRET_REF
RELAY_DATABASE_URL
RELAY_DATABASE_SECRET_REF
UPLOAD_DATABASE_URL
UPLOAD_DATABASE_SECRET_REF
GOVERNANCE_DATABASE_URL
GOVERNANCE_DATABASE_SECRET_REF
KNOWLEDGE_DATABASE_URL
KNOWLEDGE_DATABASE_SECRET_REF
EXPORT_DATABASE_URL
EXPORT_DATABASE_SECRET_REF
RETENTION_SCHEDULER_DATABASE_URL
RETENTION_SCHEDULER_DATABASE_SECRET_REF
ARCHIVE_DATABASE_URL
ARCHIVE_DATABASE_SECRET_REF
BOOTSTRAP_DATABASE_URL
BOOTSTRAP_DATABASE_SECRET_REF
DATABASE_POOL_SIZE
DATABASE_POOL_MAX_OVERFLOW
DATABASE_POOL_TIMEOUT_SECONDS
DATABASE_READINESS_TIMEOUT_SECONDS
WORKER_DATABASE_POOL_SIZE
WORKER_DATABASE_POOL_MAX_OVERFLOW
WORKER_DATABASE_POOL_TIMEOUT_SECONDS
WORKER_POLL_SECONDS
UPLOAD_LEASE_SECONDS
UPLOAD_MAXIMUM_ATTEMPTS
UPLOAD_VALIDATION_LEASE_SECONDS
UPLOAD_VALIDATION_MAXIMUM_ATTEMPTS
BULK_PREPARATION_LEASE_SECONDS
BULK_PREPARATION_MAXIMUM_ATTEMPTS
```

Retention and archive:

```text
EVENT_RETENTION_DAYS
RETENTION_ARCHIVE_EXECUTION_ENABLED
RETENTION_EXECUTION_CONTROL_FILE
RETENTION_WORKSPACE_IDS
RETENTION_CLAIM_BATCH_SIZE
RETENTION_LEASE_SECONDS
RETENTION_MAXIMUM_ATTEMPTS
RETENTION_WORKER_DATABASE_POOL_SIZE
RETENTION_WORKER_DATABASE_POOL_MAX_OVERFLOW
RETENTION_METRICS_PORT
RETENTION_WORKER_SUBJECT_ID
```

OIDC Identity:

```text
OIDC_ISSUER
OIDC_AUDIENCE
OIDC_JWKS_URL
OIDC_ALLOWED_ALGORITHMS
OIDC_PUBLIC_AUTHORITY
OIDC_PUBLIC_ORIGIN
OIDC_CLIENT_ID
OIDC_HARDWARE_ACR_VALUES
OIDC_STEP_UP_ACR
OIDC_HARDWARE_AMR_VALUES
OIDC_HARDWARE_WEBAUTHN_ENABLED
OIDC_PASSWORD_REAUTH_ACR_VALUES
OIDC_PASSWORD_REAUTH_REQUEST_ACR
OIDC_PASSWORD_AMR_VALUES
WORKSPACE_SELECTION_ENABLED
IDENTITY_ADMIN_ENABLED
IDENTITY_ADMIN_BASE_URL
IDENTITY_ADMIN_REALM
IDENTITY_ADMIN_CLIENT_ID
IDENTITY_ADMIN_CLIENT_SECRET_REF
IDENTITY_ADMIN_TIMEOUT_SECONDS
IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED
HIGH_RISK_AUTH_MAX_AGE_SECONDS
ADMIN_PASSWORD_FALLBACK_ENABLED
ADMIN_PASSWORD_FALLBACK_TTL_SECONDS
DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
```

DataHub GMS and Frontend:

```text
DATAHUB_BASE_URL
DATAHUB_SECRET_REF
DATAHUB_EXPECTED_VERSION
DATAHUB_ALLOWED_VERSIONS
DATAHUB_VERSION_ENFORCEMENT
DATAHUB_VERSION_PROBE_TTL_SECONDS
DATAHUB_TIMEOUT_SECONDS
DATAHUB_MAX_CONCURRENCY
DATAHUB_QUEUE_TIMEOUT_SECONDS
DATAHUB_CIRCUIT_FAILURE_THRESHOLD
DATAHUB_CIRCUIT_OPEN_SECONDS
DATAHUB_STALE_TTL_SECONDS
DATAHUB_CATALOG_PIT_VERIFIED
DATAHUB_CATALOG_PIT_EVIDENCE_REFERENCE
CATALOG_PROFILE_COLLECTOR_ENABLED
CATALOG_PROFILE_DATABASE_URL
CATALOG_PROFILE_DATABASE_SECRET_REF
CATALOG_PROFILE_DATAHUB_SECRET_REF
CATALOG_PROFILE_SUBJECT_ID
CATALOG_PROFILE_FRESHNESS_SLA_SECONDS
CATALOG_PROFILE_PROVIDER_CONFIG_HASH
CATALOG_PROFILE_PROVENANCE_KEY_ID
CATALOG_PROFILE_PROVENANCE_KEY_SECRET_REF
QUALITY_WORKER_ENABLED
QUALITY_DATABASE_URL
QUALITY_DATABASE_SECRET_REF
QUALITY_WORKER_SUBJECT_ID
QUALITY_WORKER_WORKSPACE_ID
QUALITY_SOURCE_MANIFEST_FILE
QUALITY_SOURCE_SECRET_ROOT
QUALITY_WORKER_FINGERPRINT
QUALITY_WORKER_LEASE_SECONDS
QUALITY_DISPATCH_MAX_DUE_SCHEDULES
QUALITY_DISPATCH_MAX_CREATED_RUNS
DATARIVER_CATALOG_SYNC_MAX_PAGES
GOVERNANCE_APPLY_LEASE_SECONDS
GOVERNANCE_APPLY_MAXIMUM_ATTEMPTS
GOVERNANCE_WORKER_SUBJECT_ID
UI_DATAHUB_URL
DATAHUB_EMBED_BASE_URL
DATAHUB_EMBED_ENABLED
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
```

Airflow, Redis Cache and Redis Delivery:

```text
UI_AIRFLOW_URL
AIRFLOW_WORKSPACE_ID
REDIS_CACHE_URL
REDIS_CACHE_SECRET_REF
REDIS_DELIVERY_URL
REDIS_DELIVERY_SECRET_REF
OUTBOX_LEASE_SECONDS
OUTBOX_MAXIMUM_ATTEMPTS
WORKER_POLL_SECONDS
CACHE_DEFAULT_TTL_SECONDS
CACHE_MAX_VALUE_BYTES
CATALOG_SEARCH_CACHE_TTL_SECONDS
CATALOG_SEARCH_MINIMUM_QUERY_LENGTH
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
```

S3-compatible storage:

```text
S3_ENDPOINT_URL
S3_PUBLIC_ENDPOINT_URL
S3_PUBLIC_ORIGIN
S3_REGION
S3_BUCKET_QUARANTINE
S3_BUCKET_ACCEPTED
S3_BUCKET_EXPORTS
S3_BUCKET_FILEFOLDER
S3_BUCKET_INFOSCHEMA
S3_ACCESS_KEY_FILE
S3_SECRET_KEY_FILE
S3_EXPORT_ACCESS_KEY_FILE
S3_EXPORT_SECRET_KEY_FILE
S3_KNOWLEDGE_ACCESS_KEY_FILE
S3_KNOWLEDGE_SECRET_KEY_FILE
S3_CORS_MANAGEMENT_MODE
S3_ARCHIVE_ENDPOINT_URL
S3_ARCHIVE_REGION
S3_ARCHIVE_BUCKET
S3_ARCHIVE_PREFIX
S3_ARCHIVE_ACCESS_KEY_FILE
S3_ARCHIVE_SECRET_KEY_FILE
S3_ARCHIVE_ENCRYPTION_PROFILE_FINGERPRINT
S3_ARCHIVE_WORKER_PRINCIPAL_FINGERPRINT
PRESIGNED_URL_TTL_SECONDS
CATALOG_EXPORT_WORKER_ENABLED
CATALOG_EXPORT_ACCESS_TTL_SECONDS
CATALOG_EXPORT_DOWNLOAD_TTL_SECONDS
CATALOG_EXPORT_LEASE_SECONDS
CATALOG_EXPORT_MAXIMUM_ATTEMPTS
CATALOG_EXPORT_PAGE_SIZE
CATALOG_EXPORT_MAXIMUM_ROWS
CATALOG_EXPORT_MAXIMUM_BYTES
UPLOAD_LEASE_SECONDS
UPLOAD_MAXIMUM_ATTEMPTS
UPLOAD_VALIDATION_LEASE_SECONDS
UPLOAD_VALIDATION_MAXIMUM_ATTEMPTS
BULK_PREPARATION_LEASE_SECONDS
BULK_PREPARATION_MAXIMUM_ATTEMPTS
EXPORT_WORKER_SUBJECT_ID
RETENTION_WORKER_SUBJECT_ID
WORKER_POLL_SECONDS
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
```

Chat, Embedding and Reranker:

```text
LOCAL_INFERENCE_SOURCE_HOST_ENABLED
LOCAL_INFERENCE_ALLOWED_HOSTS
LOCAL_OLLAMA_CHAT_ENABLED
LOCAL_OLLAMA_CHAT_BASE_URL
LOCAL_OLLAMA_CHAT_MODEL
LOCAL_OLLAMA_CHAT_TIMEOUT_SECONDS
LOCAL_OLLAMA_CHAT_CONTEXT_TOKENS
LOCAL_OLLAMA_EMBEDDING_ENABLED
LOCAL_OLLAMA_EMBEDDING_BASE_URL
LOCAL_OLLAMA_EMBEDDING_MODEL
LOCAL_OLLAMA_EMBEDDING_TIMEOUT_SECONDS
LOCAL_LLAMA_CPP_RERANKER_ENABLED
LOCAL_LLAMA_CPP_RERANKER_BASE_URL
LOCAL_LLAMA_CPP_RERANKER_MODEL
LOCAL_LLAMA_CPP_RERANKER_TIMEOUT_SECONDS
LOCAL_LLAMA_CPP_RERANKER_TOP_N
INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS
INTRANET_OPENAI_COMPATIBLE_APPROVED_PUBLIC_HOSTS
INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED
INTRANET_OPENAI_COMPATIBLE_CHAT_BASE_URL
INTRANET_OPENAI_COMPATIBLE_CHAT_MODEL
INTRANET_OPENAI_COMPATIBLE_CHAT_API_KEY_SECRET_REF
INTRANET_OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
INTRANET_OPENAI_COMPATIBLE_CHAT_CONTEXT_TOKENS
INTRANET_OPENAI_COMPATIBLE_CHAT_TEMPERATURE
INTRANET_OPENAI_COMPATIBLE_CHAT_TOP_P
INTRANET_OPENAI_COMPATIBLE_CHAT_REPETITION_PENALTY
INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLE_THINKING
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_BASE_URL
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_MODEL
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_API_KEY_SECRET_REF
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_TIMEOUT_SECONDS
INTRANET_RERANKER_ENABLED
INTRANET_RERANKER_BASE_URL
INTRANET_RERANKER_MODEL
INTRANET_RERANKER_API_KEY_SECRET_REF
INTRANET_RERANKER_TIMEOUT_SECONDS
INTRANET_RERANKER_TOP_N
CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED
CHAT_RATE_LIMIT_REQUESTS_PER_MINUTE
CHAT_RATE_LIMIT_TOKENS_PER_MINUTE
CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID
CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID
CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
SYSTEM_CONFIGURATION_SECRET_ROOT
```

Neo4j and Knowledge:

```text
NEO4J_IMAGE
NEO4J_PROJECTION_ENABLED
NEO4J_SOURCE_HOST_ENABLED
NEO4J_URI
NEO4J_ALLOWED_HOSTS
NEO4J_DATABASE
NEO4J_AUTH_SECRET_REF
NEO4J_CONNECTION_TIMEOUT_SECONDS
NEO4J_MAXIMUM_CONNECTION_POOL_SIZE
NEO4J_HTTP_PORT
NEO4J_BOLT_PORT
UI_GRAPH_URL
KNOWLEDGE_PIPELINE_ENABLED
KNOWLEDGE_SOURCE_WORKER_ENABLED
KNOWLEDGE_SOURCE_JOB_MAXIMUM_ATTEMPTS
KNOWLEDGE_SOURCE_WORKER_LEASE_SECONDS
KNOWLEDGE_SOURCE_WORKER_POLL_SECONDS
KNOWLEDGE_SOURCE_MEMORY_SPOOL_BYTES
KNOWLEDGE_SOURCE_SPOOL_DIRECTORY
KNOWLEDGE_WORKER_SUBJECT_ID
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
SYSTEM_CONFIGURATION_SECRET_ROOT
```

Observability:

```text
UI_PROMETHEUS_URL
UI_GRAFANA_URL
GRAFANA_EMBED_BASE_URL
GRAFANA_EMBED_ENABLED
GRAFANA_EMBED_EVIDENCE_REFERENCE
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS
```

## Secrets

Only reference paths belong in the environment. Keep values in ignored `secrets/`, Docker secrets,
or an orchestrator-mounted equivalent. Do not put passwords, tokens or API keys in URLs, Admin,
Git, applied-state JSON or workflow output.

The canonical container namespace is `file:/run/secrets/<name>`. Source-host launchers map the same
contract to the checkout's ignored secret directory. The managed workflow deliberately does not
read or fingerprint secret contents. Rotating a value while retaining the same reference therefore
requires the secret backend's controlled rollout or an explicit consumer force-recreation; an
unchanged `.env` reference alone cannot signal that rotation.

## Admin behavior and change propagation

Admin reads the API process's current typed snapshot. Therefore:

1. `DATARIVER_ENV_FILE` identifies the selected file and `DATARIVER_OPERATOR_PROFILE` identifies
   its lifecycle; Admin displays both from the running Settings snapshot without opening the file;
2. editing `.env` alone does not change a running process;
3. the update/restart workflow recreates affected consumers;
4. refreshing Admin then shows the new redacted effective value;
5. changing UI state never changes `.env` or a running connector;
6. connection tests accept only a known system identifier and use the server-owned snapshot and
   destination allowlist—never a browser-supplied URL, body or secret.

The **테스트 후 반영** action runs that current-snapshot probe and immediately reflects the result
as `미연결`, `연결중`, `오류` or `연결됨` in the current Admin page. An available result is shown as
`정상 연결됨`; Core/LLM group badges become green only after every configured, probeable member
passes. This is current-page probe evidence and is cleared when the inventory is refreshed. The
runtime configuration was already applied when the API process started, so this action does not
write the environment or execute a host command.

When the environment itself changes, the operator still runs the server-owned update/restart
workflow. It validates the edited file, applies migrations when required, recreates affected
consumers and runs its own post-change probes. A source-free Pilot uses `deploy_pilot.sh`; it does
not contain or invoke `workflow_update_restart.py`.

If Admin differs from the selected file, verify the workflow profile, recorded `env_file`, running
container creation time, and Compose command before changing another setting.

## Failure and recovery behavior

- The source checkout must be clean. Ignored `.env.<profile>`, secret and applied-state files do not
  make it dirty; tracked edits stop the workflow before a container mutation.
- A legacy applied-state file without fingerprints is accepted once. Every current environment key
  is treated as changed, producing a conservative first rollout, after which key-level selection is
  used.
- Unknown environment keys conservatively recreate runtime consumers but never infer a schema
  migration. Malformed state, an unknown profile or invalid Compose configuration stops before
  mutation.
- Optional API workers are recreated only when already running. Local Redis/MinIO, Airflow, Neo4j
  and APISIX are recreated only when both the applied topology selected them and a consumed key
  changed.
- State fingerprints are written only after Compose mutation, health and required provider probes
  succeed. A failure leaves the previous applied state intact. The workflow is forward-only and
  does not claim automatic rollback.

Enabling an optional worker in `.env` does not silently create a service that was not part of the
applied topology. After completing its DB role, secret and provider options, start that explicit
Compose profile once with the exact Compose files used by the deployment:

```bash
./scripts/compose.sh --env-file .env.<profile> \
  -f compose.yaml -f compose.identity.yaml \
  --profile knowledge-source up -d --wait knowledge-source-worker

./scripts/compose.sh --env-file .env.<profile> \
  -f compose.yaml -f compose.identity.yaml \
  --profile catalog-export up -d --wait catalog-export-worker

./scripts/compose.sh --env-file .env.<profile> \
  -f compose.yaml -f compose.identity.yaml \
  --profile retention-archive up -d --wait \
  retention-scheduler retention-archive-worker
```

Do not copy the file list blindly to an offline or external-identity topology; use its recorded
Compose set. Once a selected worker is running, `workflow_update_restart.py` detects relevant
environment changes and recreates only that running consumer.

For a same-reference secret rotation, use the equivalent controlled orchestrator rollout. A local
Compose example for the core runtime is:

```bash
./scripts/compose.sh --env-file .env.<profile> \
  -f compose.yaml -f compose.identity.yaml \
  up -d --wait --no-deps --force-recreate \
  api outbox-relay upload-worker upload-validation-worker governance-apply-worker
```

Select only actual consumers and the exact compose-file set recorded for that topology. For local
MinIO or Redis, use `compose.local-connectors.yaml` and recreate only `minio`, `redis-cache` or
`redis-delivery`. A private deployment should prefer its secret manager's atomic rotation/rollout
procedure.
