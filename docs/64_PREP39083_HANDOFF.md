# PREP39083 one-command source deployment

## Fixed release identity and boundary

The machine-readable accepted release is
`deploy/prep39083/release.json`. At this checkpoint it identifies:

```text
Product  a09cd4cb47db7bb31f608dfd94c61f34844d33af
Evidence 07d6344ab287fa83c4611c780d3c8a23f8ffb878
Platform linux/amd64
Port     39083
Project  datariver-prep39083
```

The CLI resolves the current committed handoff HEAD itself and reuses
`prep39083_release.py` for Product/Evidence ancestry and runtime-input validation. Operators do not
set `PRODUCT_SHA`, `IMAGE_REF`, image tags, ports, project names, Workspace IDs or service Subject
IDs in a shell.

## Normal operator path

Update the source checkout on the WSL Linux filesystem:

```bash
git switch dev
git pull --ff-only origin dev
```

On the first installation only, create the target-owned operator configuration:

```bash
install -m 0600 deploy/prep39083/.env.prep.example deploy/prep39083/.env.prep
editor deploy/prep39083/.env.prep
```

For every initial deployment and later release update, run exactly one command:

```bash
./scripts/prep39083 deploy
```

The ignored `.env.prep` is never changed by Git or the deployer. Missing core external values fail
with key names only. Fixed/default values are derived from the tracked contract. The deployer first
classifies containers, network, named volumes, the runtime-secret file and accepted receipt. It
creates a mode-0600 `.env.prep.runtime` only after proving the target is fresh or a failed first
install is disposable. Accepted deployments always reuse their existing secrets. Legacy generated
secrets still present in an older `.env.prep` are migrated without modifying that file and must
match on later runs.

The deploy command performs source validation, environment/proxy merge, native amd64 preflight,
39080 observation, Compose validation, exact image build/inspection, read-only external-provider
preflight, deployment-attempt ownership, local service health, idempotent schema initialization,
DB credential verification, admin/requested-service bootstrap, web health, staged feature-aware
authenticated smoke and final 39080 re-observation. The same command
handles a clean host, an accepted running or stopped stack, an exact-release rerun and a safely
provable failed first install. A failed smoke is resumed by the same command without deleting or
resetting its owned state. It never runs `down -v`, deletes a volume or widens authorization.

If no administrator exists, the same command prompts for username, hidden password and confirmation.
If an administrator exists, it prompts only for that administrator's hidden smoke password. The
password exists only in memory and one short-lived mode-0600 file and is never written to an env,
Git, log or Evidence.

## Environment ownership

| File | Owner | Contents | Update behavior |
|---|---|---|---|
| `.env.prep` | PREP operator | public origin, build proxy, providers, optional runtime proxy/CA and Studio read-only URL | preserved |
| `.env.prep.runtime` | deployer | PostgreSQL/Neo4j/MCP secrets, Product image identity, fixed PREP topology, K9/MCP Subject and Workspace | generated/reused |
| `.env.prep.optional` | PREP operator | optional Airflow/MinIO, MCL and Grafana settings | absent is valid |
| `env-contract.json` | Product source | key ownership, defaults, fixed topology and required `NO_PROXY` entries | updated by Git |
| `release.json` | release handoff | accepted Product/Evidence/platform/port/project | updated by Git |

`POC_K9_STUDIO_DATABASE_URL` remains operator-owned because it must name an approved external
read-only Knowledge Studio connection. It is feature-dependent, not core-required. A configured
URL derives `POC_K9_SCHEDULER_ENABLED=true`, requires the K9 Subject and DAILY managed-graph READY
smoke, and preserves the existing managed-refresh contract. A blank URL derives `false`; core web,
login, DataHub and Chat smoke continue and the summary reports `K9 Managed Refresh: DEFERRED —
Studio DB not configured`. No URL or Studio state is fabricated.

The local Workspace is the Product's canonical target-local Workspace. MCP remains a built-in
adapter with a generated target-local token and deterministic Subject, so it adds no operator
secret. When K9 is configured, K9 and MCP use distinct deterministic Subjects; each requested
Subject is created-if-absent, verified-if-present and fails on drift.

Optional integrations are enabled only when needed:

```bash
install -m 0600 deploy/prep39083/.env.prep.optional.example \
  deploy/prep39083/.env.prep.optional
editor deploy/prep39083/.env.prep.optional
./scripts/prep39083 deploy
```

MCL remains disabled by default. Airflow and MinIO are not needed by core boot or the managed-graph
smoke; configure them only for Registration acceptance. DataHub and all three inference stages stay
external and are never added to this Compose project.

## Corporate proxy contract

`HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` are build/toolchain settings. The wrapper injects
uppercase and lowercase variants into `uv`, Docker build and npm only. The deployer preserves the
operator build `NO_PROXY`, adds `127.0.0.1`, `localhost`, `pgvector`, `redis`, `neo4j` and `web`, and
performs the host health probe with an explicit proxy bypass. These generic build values are not
injected into the running web service.

Product provider routing is separate and explicit. Blank `POC_RUNTIME_HTTP_PROXY` and
`POC_RUNTIME_HTTPS_PROXY` mean direct DataHub/Chat/Embedding/Reranker connections even when the
build proxy is configured. When a runtime proxy is required, set those keys and use
`POC_RUNTIME_NO_PROXY` for exact hosts/IPs, domain suffixes, or optional ports that must stay direct.
`RUNTIME_CA_CERT_FILE` optionally names one target-local CA bundle; the deployer mounts it read-only
and never commits it. The pinned Node runtime uses one shared explicit provider transport and never
disables global TLS verification.

Compose passes Docker's predefined proxy build arguments. The Dockerfile derives npm proxy use
inside the dependency-installation layer, uses one temporary npmrc, bounds `strict-ssl=false` to
that step, restores it to true and deletes the npmrc in the same layer. Proxy values are not image
ENV, labels, Evidence or command output.

## Operations and diagnostics

The following are optional troubleshooting/operations commands, not normal deployment steps:

```bash
./scripts/prep39083 doctor
./scripts/prep39083 status
./scripts/prep39083 logs
./scripts/prep39083 smoke
./scripts/prep39083 export
```

All Python execution goes through the wrapper's `uv run --frozen`; system Python package state is
not part of the operator contract.

### Database credential mismatch

`PREP_LOCAL_DB_CREDENTIAL_MISMATCH` means the Compose web credential does not authenticate to the
existing PostgreSQL volume. It is not the human administrator password. PostgreSQL initialization
passwords apply only when a volume is first created, so changing an env value alone does not rotate
an existing role.

- When `runtime/prep39083/accepted.json` exists, never reset the volume or password. Restore the
  accepted target-local runtime secret from its approved target backup and rerun deploy.
- A safe non-destructive one-line recovery with such a backup is:

  ```bash
  install -m 0600 /approved/backup/.env.prep.runtime deploy/prep39083/.env.prep.runtime && ./scripts/prep39083 deploy
  ```

- With no accepted or attempt receipt, the deployer first checks whether an older handoff produced
  the exact canonical bootstrap/runtime footprint described below. Otherwise it uses the
  PostgreSQL container's local-socket administrator path to inspect every public table and accepts
  automatic credential reconciliation only when all are empty. A non-bootstrap residual Neo4j
  volume must also be empty and accessible with a preserved runtime or legacy credential. This
  repair changes only the empty local PostgreSQL role credential, never a volume.
- Any unowned durable row/node, malformed receipt, missing accepted secret, unknown project
  service/volume, or state that cannot be proved empty or canonically deployment-owned fails closed as
  `PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY`. The deployer never chooses `down -v`, volume
  removal or database reset.

## Retry receipt and unified target states

Immediately before the first deployment-owned persistent mutation, the deployer atomically writes
ignored mode-0600 `runtime/prep39083/deploy-attempt.json`. It binds Product, Evidence, handoff,
project, volume identities, K9 mode and a versioned HMAC target-ownership fingerprint without
storing any secret. The ownership fingerprint covers only the generated PostgreSQL, Neo4j and MCP
target secrets. Tracked `FIXED` release configuration is deliberately excluded: a descendant
release may change it without pretending that the target or its volumes changed. Project,
linux/amd64 platform, port 39083, K9 mode, canonical volume identities, and Product/Handoff ancestry
remain separately fail-closed. Its phase advances through state services, schema, bootstrap, web
and smoke. A matching unfinished receipt is `EXISTING_OWNED_INCOMPLETE`; the same command reruns
idempotent gates and reuses the existing admin, service Subjects, credentials and volumes.

For an unfinished deployment, the deployer reads the preserved runtime file and validates receipt
ownership plus source ancestry before reconciling or writing the descendant release's tracked
`FIXED` values. A legacy V1 receipt is validated against the historical environment contract at its
recorded Handoff commit and then migrated atomically to the V2 ownership-only receipt. This remains
valid when an earlier failed deploy already wrote descendant `FIXED` values: historical values are
reconstructed for V1 verification while the preserved generated secrets and canonical volumes are
verified unchanged. Malformed/unrelated receipts, secret drift, volume drift, topology drift,
invalid ancestry, or K9-mode drift still stop without mutating the runtime file.

Handoffs predating the receipt are recognized only when the existing bootstrap inspector proves
the exact canonical administrator/MCP/K9 identity shape, no active session or unexpected business
state, canonical K9 policies/runs, and Neo4j data confined to those managed run namespaces. This
bounded state is `LEGACY_SELF_BOOTSTRAPPED_PARTIAL`. Any drift remains fail-closed.

The internal state machine is deterministic and does not infer database state from whether a
container happens to be running:

| State | Evidence | Deploy behavior |
|---|---|---|
| `FRESH_CLEAN` | no receipt, runtime secret, project container, network or volume | generate once, create state services, bootstrap |
| `EXISTING_ACCEPTED_RUNNING` | valid receipt/runtime plus required volumes; project running | reuse, migrate, reconcile |
| `EXISTING_ACCEPTED_STOPPED` | valid receipt/runtime plus required volumes; project stopped | reuse, start, migrate, reconcile |
| `EXISTING_OWNED_INCOMPLETE` | no accepted marker; exact unfinished attempt receipt/runtime/volumes | resume idempotently; preserve all state |
| `LEGACY_SELF_BOOTSTRAPPED_PARTIAL` | pre-receipt canonical bootstrap/runtime footprint only | bind an attempt receipt and resume |
| `FAILED_FIRST_INSTALL_RECOVERABLE` | no receipt and all residual durable stores proven empty | non-destructive credential reconcile, then normal deploy |
| `EXISTING_STATE_AMBIGUOUS` | receipts/secrets/state disagree or durable state exists | fail closed; no automatic mutation |

## Provider preflight and smoke diagnostics

The exact built image performs bounded DataHub, Chat, Embedding and Reranker requests before the
attempt receipt and any Product-owned durable mutation. A configured Studio DB receives a read-only
connection/`SELECT 1`; absent Studio configuration remains K9 DEFERRED. These checks use configured
exact endpoints rather than assuming `/health` or `/models`.

The tracked Product and Chat preflight share the fixed `POC_LLM_TIMEOUT_MS=120000` per-call policy.
It is derived from `env-contract.json`, not requested from the PREP operator. The authenticated
smoke retains a 300,000 ms outer HTTP envelope so the bounded AUTO classifier and GENERAL composer
can complete sequentially without overriding either Product call deadline. Product timeout,
authentication, connectivity, provider HTTP and response-contract failures remain distinct
sanitized smoke classifications; a GENERAL route/evidence mismatch remains
`PREP_SMOKE_GENERAL_ROUTE_FAILED`.

Authenticated smoke emits stage progress and bounded heartbeats instead of hiding a long captured
subprocess. Failures are classified as DataHub connectivity/auth, K9/semantic readiness, GENERAL
provider/route, or administrator authentication. Sanitized failure metadata is stored in ignored
`runtime/prep39083/smoke-failure.json`; it contains no URL, credential, token or response body and
is superseded by the next successful smoke.

### Manual Compose inspection

The effective environment is intentionally private and ephemeral. Use the CLI for status and logs.
If deeper diagnosis is required, first run `doctor`; do not recreate a raw `docker run` bootstrap
with separately typed PostgreSQL variables. Bootstrap always uses `docker compose run --no-deps`
from the exact web service so its DB user/password/network match the running Product contract.

### Separate acceptance suites

Startup runs only the bounded smoke. Router 60, Boundary 8 and MCP/auth remain explicit PREP
acceptance gates after browser acceptance; they are not added to every daily deployment. Use the
tracked verifier scripts with a PREP-owned short-lived credential and remove that credential after
acceptance.

### Stop and rollback

Use `docker compose stop` through an approved diagnostic procedure; never use
`docker compose down -v`. Rollback selects the previous approved exact image/configuration backup
and uses `up -d --no-build`. Before schema-affecting changes, back up PostgreSQL and Neo4j. The POC
state initializer is additive and idempotent but is not a downgrade mechanism.
