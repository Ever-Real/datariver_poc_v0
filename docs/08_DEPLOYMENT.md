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
| `compose.airflow.yaml` | Airflow 3.3 API server, scheduler, DAG processor, triggerer and init using LocalExecutor/isolated DB role | scheduled scan/probe only |
| `compose.gateway.yaml` | APISIX 3.17 standalone configuration | local gateway/rate limit/health-check profile |
| `semiconductor-seed` profile | deterministic one-shot seed command | explicit non-production data |

No Compose file starts DataHub. OPA, a separate graph database and a full observability stack are documented extension seams, not shipped runtime dependencies in this baseline.

The supported production DataHub provider contract is stable `v1.6.0`. The external deployment
owner must use the component OCI index digests in
[`infra/contracts/datahub-v1.6.0-images.json`](../infra/contracts/datahub-v1.6.0-images.json), not the
mutable `head`, `latest` or RC tags. DataRiver production sets
`DATAHUB_VERSION_ENFORCEMENT=enforce`; development may use `report` only to expose a degraded
capability while an external stack is being upgraded.

Run `uv run python scripts/verify_datahub_contract.py --base-url <target-datahub-url>` during
promotion. A successful version probe is only the first gate; the live provider contract tests
listed below remain mandatory.

## Configuration and bootstrap

Bootstrap requires a DataHub token and generates ignored, permission-restricted secret files plus `.env` and the runtime Keycloak realm:

```bash
./scripts/bootstrap.sh '<datahub-token>'
# or: ./scripts/bootstrap.ps1 -DataHubToken '<datahub-token>'
```

Bootstrap is idempotent for infrastructure credentials: an existing non-empty secret is preserved, while the supplied DataHub token and derived SeaweedFS/Keycloak files are refreshed. Deliberate credential rotation follows the runbook and is not coupled to ordinary bootstrap.

Set `DATAHUB_BASE_URL` and review origins/ports in `.env`. The production validator rejects wildcard CORS, HTTP external URLs, password-bearing URLs and seed activation. Only `file:` secret references are implemented; a Vault/KMS adapter is a separate deployment integration.

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

- Loopback development ports: web `8080`, API `8000`, Keycloak `8081`, APISIX `9080`, Airflow `8082` when their overlays are enabled.
- PostgreSQL, Valkey and object-service internals stay on the private `data` network and have no host bind in the core file.
- API has an RLS-constrained database role; migration owns DDL. Relay, upload, governance and bootstrap have distinct least-privilege database identities and service-specific secret mounts. Airflow and Keycloak have distinct databases/roles.
- APISIX standalone mode has no administration/control port and does not replace application ABAC.
- APISIX and web run non-root with read-only root filesystems. APISIX renders configuration and request temp files only into bounded, non-executable tmpfs; its health check executes a real proxied HTTP request rather than trusting a process-only command.
- Web Nginx uses Docker's embedded DNS resolver for the API upstream. API container replacement therefore does not require web restart and must be included in recovery acceptance.
- Production exposes only a TLS edge. Direct local API/identity ports must be removed or firewalled by the environment override.

## Worker correctness

- PostgreSQL outbox is canonical. Relay publishes IDs to queue Valkey; failed events are individually retried, dead-lettered after the configured maximum and exposed in operations. Published outbox and completed inbox rows are not automatically pruned until the governed WORM/Legal-Hold/Maker-Checker retention gate is implemented and accepted.
- Cache Valkey has bounded volatile memory and `allkeys-lfu`; queue Valkey is separate, `noeviction`, AOF-backed. They never share a URL/database.
- Upload completion reconciles an already-completed multipart operation via object `HEAD`. Validation streams chunks and promotes with copy-before-manifest-commit; a stale quarantine duplicate is safe to clean later.
- Governance application uses a PostgreSQL job/attempt lease. Transient DataHub failures back off automatically; terminal/mismatched content reaches `APPLY_FAILED` and requires authorized requeue.

## Airflow boundary

Both included DAGs are paused at creation. `datariver_catalog_probe` performs a read probe; `datariver_catalog_sync` calls the versioned page-sync API and never writes application tables. Bootstrap creates the confidential `datariver-airflow` Keycloak client and its mounted client secret. Tasks obtain and refresh short-lived `client_credentials` tokens; no long-lived bearer token is stored. The application membership grants only `catalog.search`, `catalog.read` and `catalog.sync` for the selected workspace.

The Compose overlay intentionally uses Airflow `SimpleAuthManager` only for loopback development and pre-creates its password file from a secret. Any shared or production deployment must replace it with an environment-supported enterprise/FAB SSO configuration and retest authorization; the DataRiver service-token flow is independent of that human UI login choice.

## Database and object operations

- Alembic has one head at `0012`: the generated current initial schema plus conditional compatibility bridges for local databases that applied earlier revisions. Deployment runs migration before API/workers. The API role can only read `public.alembic_version` for readiness; migration ownership remains separate.
- PostgreSQL pool size/overflow/lease timeout, statement timeout, idle-transaction timeout and application names are explicit. Budget `API replicas × (API pool + overflow) + long-running workers × (worker pool + overflow) + one-shot/IdP/Airflow/admin reserve`; current one-API/four-worker defaults have a ceiling of 60 before reserve.
- Liveness is process-only. Readiness leases the API pool and requires exactly packaged Alembic head `0012`; Compose and APISIX use readiness for upstream health.
- `scripts/probe_pgbouncer_rls.py` and its unit contract implement the pre-adoption transaction-pool leakage gate. No Compose profile currently deploys PgBouncer and no live pooler pass has been recorded; direct PostgreSQL remains the supported path until the isolated two-workspace probe succeeds.
- Back up PostgreSQL and SeaweedFS as a consistency set or record a watermark; restore into isolation and follow the drill in [operations runbook](13_OPERATIONS_RUNBOOK.md) before traffic.
- Accepted-object retention/lifecycle is environment policy. Quarantine receives a shorter cleanup policy, but never delete an object whose manifest is actively leased.
- Initial recovery targets (RPO <= 5 minutes, RTO <= 60 minutes) are objectives until an environment drill records measured evidence.

The assistant inference module is not a deployed runtime component. It has a disabled adapter and a
typed pre-authorized input/output contract only; Compose mounts no provider endpoint or inference
secret and creates no inference queue/job. Provider integration, durable dispatch, SSE, pre/post-call
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

SeaweedFS remains the local/Pilot upload implementation. Immutable archive production promotion uses
the separate port and evidence gate in ADR-0012; no checked-in product label or Object Lock setting
is treated as WORM acceptance.

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
