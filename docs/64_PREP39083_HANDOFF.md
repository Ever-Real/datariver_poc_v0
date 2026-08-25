# PREP39083 one-command source deployment

## Fixed release identity and boundary

The machine-readable accepted release is
`deploy/prep39083/release.json`. At this checkpoint it identifies:

```text
Product  fab42bd03eb8cbe9b3bcbff6c4cfdb2cf5e5fc6c
Evidence 5761754d3a09b714b31f5430744e8b9da6b15136
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
39080 observation, Compose validation, exact image build/inspection, local service health,
idempotent schema initialization, DB credential verification, admin/requested-service bootstrap,
web health, feature-aware authenticated smoke and final 39080 re-observation. The same command
handles a clean host, an accepted running or stopped stack, an exact-release rerun and a safely
provable failed first install. It never runs `down -v`, deletes a volume or widens authorization.

If no administrator exists, the same command prompts for username, hidden password and confirmation.
If an administrator exists, it prompts only for that administrator's hidden smoke password. The
password exists only in memory and one short-lived mode-0600 file and is never written to an env,
Git, log or Evidence.

## Environment ownership

| File | Owner | Contents | Update behavior |
|---|---|---|---|
| `.env.prep` | PREP operator | public origin, proxy, DataHub, Chat, embedding, reranker, optional Studio read-only URL | preserved |
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

Enter `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` once in `.env.prep`. The wrapper injects uppercase
and lowercase variants into `uv` and its child processes. The deployer preserves operator
`NO_PROXY`, adds `127.0.0.1`, `localhost`, `pgvector`, `redis`, `neo4j` and `web`, and performs the
host health probe with an explicit proxy bypass.

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

- With no accepted receipt, the deployer uses the PostgreSQL container's local-socket administrator
  path to inspect every public table and accepts automatic credential reconciliation only when all
  are empty. A residual Neo4j volume must also be empty and accessible with a preserved runtime or
  legacy credential. This repair changes only the empty local PostgreSQL role credential, never a
  volume.
- Any durable row/node, malformed receipt, missing accepted secret, unknown project service/volume,
  or state that cannot be proved empty fails closed as
  `PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY`. The deployer never chooses `down -v`, volume
  removal or database reset.

## Unified target states

The internal state machine is deterministic and does not infer database state from whether a
container happens to be running:

| State | Evidence | Deploy behavior |
|---|---|---|
| `FRESH_CLEAN` | no receipt, runtime secret, project container, network or volume | generate once, create state services, bootstrap |
| `EXISTING_ACCEPTED_RUNNING` | valid receipt/runtime plus required volumes; project running | reuse, migrate, reconcile |
| `EXISTING_ACCEPTED_STOPPED` | valid receipt/runtime plus required volumes; project stopped | reuse, start, migrate, reconcile |
| `FAILED_FIRST_INSTALL_RECOVERABLE` | no receipt and all residual durable stores proven empty | non-destructive credential reconcile, then normal deploy |
| `EXISTING_STATE_AMBIGUOUS` | receipts/secrets/state disagree or durable state exists | fail closed; no automatic mutation |

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
