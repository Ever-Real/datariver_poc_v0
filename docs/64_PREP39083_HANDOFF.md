# PREP39083 one-command exact-artifact deployment

## Fixed release identity and boundary

The machine-readable accepted release is
`deploy/prep39083/release.json`. At this checkpoint it identifies:

```text
Product  1ad090d084b34906438e281ee208f9ec49d9a95f
Evidence 32af64f84bb0140cc53bdae1674acff489570c69
Platform linux/amd64
Port     39083
Project  datariver-prep39083
```

The CLI resolves the current committed handoff HEAD itself and reuses
`prep39083_release.py` for Product/Evidence ancestry and runtime-input validation. Operators do not
set `PRODUCT_SHA`, `IMAGE_REF`, image tags, ports, project names, Workspace IDs or service Subject
IDs in a shell.

## Normal operator path

`origin/dev` is the development integration source. `origin/main` is the controlled PREP promotion
source and advances only by fast-forward to an already verified Handoff. For the first local
checkout where `main` does not exist:

```bash
git fetch origin main
git switch --track -c main origin/main
./scripts/prep39083 deploy
```

For every later PREP update:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
./scripts/prep39083 deploy
```

On the first installation only, create the target-owned operator configuration:

```bash
install -m 0600 deploy/prep39083/.env.prep.example deploy/prep39083/.env.prep
editor deploy/prep39083/.env.prep
```

Before the first deploy of a promoted Handoff, copy the separately delivered approved archive to
the exact ignored path recorded by `release.json`, preserving its filename. The tracked manifest
binds its SHA-256, image reference, linux/amd64 child manifest digest, config digest and OCI
revision. Do not commit the archive or substitute a locally rebuilt image.

After the checkout and exact archive are staged, the Product deployment itself remains exactly one
command:

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
39080 observation, Compose validation, exact archive checksum/content inspection, image load and
manifest/platform/revision inspection, read-only external-provider
preflight, deployment-attempt ownership, local service health, idempotent schema initialization,
DB credential verification, admin/requested-service bootstrap, web health, staged feature-aware
authenticated smoke and final 39080 re-observation. The same command
handles a clean host, an accepted running or stopped stack, an exact-release rerun and a safely
provable failed first install. A failed smoke is resumed by the same command without deleting or
resetting its owned state. It never runs `down -v`, deletes a volume or widens authorization.

The interactive parent shell is not a Product configuration source. Child Git/Docker/Compose/Node
commands inherit only the reviewed host execution keys (`PATH`, bounded user/temp/locale keys, and
Docker engine/context/TLS configuration) plus the canonical effective environment rendered from
the tracked contract, target-owned files, and `release.json`. Ambient `POC_*`, `DATAHUB_*`,
`LLM_*`, `AIRFLOW_*`, `MINIO_*`, `S3_*`, `GRAFANA_*`, database, `COMPOSE_*`, and
`DOCKER_DEFAULT_PLATFORM` values are ignored. Compose is invoked with an explicit project, file,
and private env file. Before either doctor or deploy loads an image, the resolved project, exact
Product tag/revision, archive checksum, child manifest, linux/amd64 platform, Web/state port
bindings, no-build policy, and canonical provider environment are verified without printing their
values. Missing or mismatched artifacts fail closed; there is no build or pull fallback.

If no administrator exists, the same command prompts for username, hidden password and confirmation.
If an administrator exists, it prompts only for that administrator's hidden smoke password. The
password exists only in memory and one short-lived mode-0600 file and is never written to an env,
Git, log or Evidence. On first installation only, the disposable bootstrap container runs as
container root so it can read a root-operator-owned mode-0600 bind mount. This does not change the
Web runtime user, add privilege, expose the Docker socket or add a host write mount. Existing-admin
reconciliation does not elevate the container user or mount the password file.

## Environment ownership

| File | Owner | Contents | Update behavior |
|---|---|---|---|
| `.env.prep` | PREP operator | private intranet origin, build/runtime network, DataHub/inference providers, DataHub Kafka connectivity, and optional exact read-only GlossaryTerm smoke URN | preserved |
| `.env.prep.runtime` | deployer | PostgreSQL/Neo4j/MCP secrets, Product image identity, fixed PREP topology, K9/MCP Subject and Workspace | generated/reused |
| `.env.prep.optional` | PREP operator | optional existing Airflow/MinIO and Grafana settings | absent is valid |
| `env-contract.json` | Product source | key ownership, defaults, fixed topology and required `NO_PROXY` entries | updated by Git |
| `release.json` | release handoff | Product/Evidence/platform/port/project plus exact promoted archive/checksum/manifest/config identity | updated by Git |

The two default K9 managed graphs are built-in Product policies. The deployer always bootstraps the
distinct K9 service Subject, reconciles those exact policy pins in local PostgreSQL, performs the
initial shared-snapshot refresh into local Neo4j, and requires both graphs plus the semantic index
to be DAILY and READY. No unrelated Studio database or extra container is required.

DataHub v1.6.0 does not expose a reliable global metadata-generation token on the Product's source
APIs. K9 therefore requires two consecutive complete inventory/metadata/lineage fingerprints to
match before semantic materialization or graph promotion. It performs at most three complete
observations. Repeated drift is `K9_SOURCE_DRIFT_RETRY_EXHAUSTED`; the mixed candidate is never
published and the prior LKG remains current.

A terminal refresh failure finalizes every unfinished canonical managed-graph policy with a
durable typed `K9_*` error instead of leaving it indefinitely `PENDING`. The active last-known-good
generation and promoted Neo4j projection remain unchanged. The semantic index reports READY only
when it belongs to the active matching generation, and authenticated smoke fails immediately on a
terminal Product error instead of waiting for the generic readiness timeout.

The local Workspace is the Product's canonical target-local Workspace. MCP remains a built-in
adapter with a generated target-local token and deterministic Subject, so it adds no operator
secret. K9 and MCP use distinct deterministic Subjects; each requested
Subject is created-if-absent, verified-if-present and fails on drift.

Optional integrations are enabled only when needed:

```bash
install -m 0600 deploy/prep39083/.env.prep.optional.example \
  deploy/prep39083/.env.prep.optional
editor deploy/prep39083/.env.prep.optional
./scripts/prep39083 deploy
```

MCL Change History uses the Kafka cluster belonging to the configured DataHub. The operator supplies
only the broker connectivity/auth/TLS values that cannot be learned through DataHub. The Product
discovers the cluster ID, one exact versioned MCL topic, GMS-internal (preferred) or explicitly
configured external Schema Registry, exact value subject, latest schema hash, DataHub version, and
source identity. The sanitized discovery receipt and durable checkpoint are target-local. A new
source begins at the earliest retained offset; an existing accepted checkpoint is never reset.
Each consume transaction remains bounded by `POC_MCL_MAX_MESSAGES`. At server startup the single
advisory-lock owner repeats bounded batches, yielding between them, until it reaches the captured
Kafka high watermark; a large retained backlog therefore continues in the background instead of
waiting for the next daily boundary. Shutdown finishes the current bounded batch and starts no
new one. A checkpoint behind Kafka retention is `HISTORY_GAP_BLOCKED` and is never advanced or
silently skipped.

Capture failures persist only bounded classification, stage, and detail identifiers in the
versioned runtime status. Raw exception text, provider response bodies, schema bodies, credentials,
tokens, and connection strings are never diagnostic fields. The durable diagnostic write is
awaited and version-verified; it does not reset the ledger, checkpoint, or discovered source
identity.

## Current hotfix evidence

The current development Handoff adds the locally verified Wave C knowledge workflows recorded
in [`docs/evidence/wave-c-knowledge-workflows/README.md`](evidence/wave-c-knowledge-workflows/README.md).
Its exact ignored archive is pinned by `release.json`; TEST PC validation is
`BLOCKED_EXTERNAL`, and this development Handoff does not claim Actual PREP or
OPS execution. The canonical deployment command and all existing no-build,
ownership, schema-integrity, provider, smoke, and non-destructive resume
contracts remain unchanged.

The preceding Wave B core user-workflow evidence remains at
[`docs/evidence/wave-b-core-user-workflows/README.md`](evidence/wave-b-core-user-workflows/README.md).

The current hotfix evidence is
[`docs/evidence/prep-unknown-state-portability-correction/README.md`](evidence/prep-unknown-state-portability-correction/README.md).
It records accepted-state provenance, Product-owned PostgreSQL integrity, non-current Dataset
exclusion, the K9 source-consistency fence, focused/source gates, the exact Product artifact, and
the preserved TEST accepted-state redeploy result. The target is a TEST PC, not Actual PREP; this
Handoff does not claim Actual PREP or OPS execution.

The preceding root-operator bootstrap evidence remains at
[`docs/evidence/prep-root-operator-bootstrap-portability/README.md`](evidence/prep-root-operator-bootstrap-portability/README.md).

The preceding release-contract evidence remains at
[`docs/evidence/prep-exact-oci-artifact-promotion/README.md`](evidence/prep-exact-oci-artifact-promotion/README.md).
It records the local-index versus registry-digest classification, approved archive transport,
fail-closed negative gates and the remove→load→inspect proof reused by this descendant.

The preceding Product recovery narrative is
[`docs/evidence/prep-k9-glossary-assignment-reconciliation/README.md`](evidence/prep-k9-glossary-assignment-reconciliation/README.md).
It records the bounded correction for the operator-provided Actual PREP failure
`K9_DATAHUB_SOURCE_FAILED / METADATA_COLLECTION / ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT`. A complete
glossary search is no longer treated as the sole canonical existence authority: each sorted unique
missing assigned Term is resolved by exact URN through DataHub, checked for exact Glossary Term
identity and existence, normalized through the same Term path, and hydrated without dropping its
assignment. Null, removed, or incompatible results fail closed as
`DANGLING_GLOSSARY_ASSIGNMENT`; provider faults retain their typed classification.

The exact integrated parent Product reproduces the retained failure after health, login, and
DataHub smoke pass. The exact descendant then performs one direct recovery, reaches both managed
graphs and semantic index READY, preserves the MCL checkpoint, completes GENERAL, and finishes
`ACCEPTED` through the same deploy flow. Runtime secrets, one administrator, K9/MCP identities,
LKG, and 39080 are preserved; disposable container, volume, and network residue is zero. The exact
image is linux/amd64 and carries the Product revision.

The preceding integrated K9/MCL evidence remains at
[`docs/evidence/prep-recovery-k9-mcl/README.md`](evidence/prep-recovery-k9-mcl/README.md).
It records the generic metadata identity profile, active-retry visibility correction, and the
independently verified MCL normalization delta that this K9-only descendant leaves unchanged.

The MCL correction is the exact Product delta previously verified at Product
`16ad344e7bde7ec060816a04b4f40aab40f28097`. It accepts the supported DataHub v1.6.0 record
representations, persists only bounded record-shape diagnostics, and replays a rejected retained
offset without checkpoint advance or duplicate append. Its standalone Evidence is commit
`ed5f21015772f913f181a6e2e316226f832744a7` in the quarantined MCL candidate lineage; all integrated
claims and exact source/hash checks are recorded in the current in-lineage recovery Evidence above.

The preceding metadata-only evidence remains at
[`docs/evidence/prep-k9-metadata-collection-hotfix/README.md`](evidence/prep-k9-metadata-collection-hotfix/README.md).
It records the earlier bounded DataHub v1.6.0 Tag projection correction and its source/runtime
gates.

The preceding source-stage diagnostic evidence remains at
[`docs/evidence/prep-k9-source-diagnostic-hotfix/README.md`](evidence/prep-k9-source-diagnostic-hotfix/README.md).
It records the five DataHub source substages, durable bounded high-level detail, deterministic
transient retry policy, semantic/LKG preservation, and the prior exact disposable resume gate.

The previous one-time Migration/K9/MCL closure evidence remains at
[`docs/evidence/prep-hotfix-migration-k9-mcl/README.md`](evidence/prep-hotfix-migration-k9-mcl/README.md).
It records the 54-file fail-open remediation, definition-level squashed-baseline compatibility,
the same exactly-once Audit 2 final PASS, terminal K9 failure propagation, MCL durable diagnostics,
historical accepted upgrade, and its completed isolated Docker fixtures. This K9-only release does
not reopen or repeat that broad Migration audit.

Accepted migration history is checksum-protected and immutable under
[`docs/68_MIGRATION_GOVERNANCE_AND_INTEGRITY.md`](68_MIGRATION_GOVERNANCE_AND_INTEGRITY.md).
An ordinary release with no migration-source change runs the integrity/static gate and a
representative supported upgrade; it does not repeat the historical 54-file audit.

Kafka bootstrap reachability does not prove that the cluster is usable: Kafka may advertise a
broker DNS name or address that PREP cannot resolve or reach after the initial bootstrap
connection. Doctor reports that as the typed Kafka connectivity/cluster stage. Correct the
DataHub-owned advertised-listener/network route; DataRiver does not deploy a second Kafka and does
not rewrite the remote Kafka configuration.

Quality Read uses GX-produced DataHub Assertion definitions/results through GMS. A zero assertion
count is a valid READY result. Quality Execution remains DEFERRED unless the existing external
Airflow `datariver_quality_dispatch` path is configured; DataRiver never deploys a second GX.
Airflow and MinIO stay optional external integrations.

## Intranet HTTP boundary

PREP/OPS intentionally support `http://<intranet-IP>:39083`. Compose publishes only the web service
on `0.0.0.0:39083`; PostgreSQL, Neo4j and Redis host ports remain bound to `127.0.0.1`. HTTP origins
must use a literal IP. Literal loopback, RFC1918 and IPv6-ULA addresses are accepted by default. If
the reviewed company intranet uses another address range, set the operator-owned
`POC_INTRANET_HTTP_ALLOWED_CIDRS` to one or more exact comma-separated IPv4/IPv6 CIDRs. Blank adds
no range; a single PREP host can be bounded with `/32` (or `/128` for IPv6). Malformed, wildcard,
unbounded, unspecified and multicast ranges fail closed. The browser Origin must still match
`POC_PUBLIC_ORIGIN` exactly, so this setting does not relax login, session, CSRF, workspace, or
asset authorization. HTTPS behavior is unchanged.

DataRiver publishes `0.0.0.0:39083` inside Docker/WSL only. Under WSL2 default NAT, company-LAN
access may additionally require an operator-reviewed Windows port-forwarding rule and Windows
Firewall rule. Windows 11 mirrored WSL networking can provide direct LAN connectivity subject to
Hyper-V and Windows Firewall policy. `./scripts/prep39083 deploy` never changes Windows Firewall,
Hyper-V policy or `netsh`; those host controls remain outside Product deployment authority.

## Corporate proxy contract

`HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` are toolchain settings retained for `uv` and host
connectivity. PREP does not build the Product image. The DEV artifact build may pass bounded proxy
arguments to Docker/npm, but they are not image runtime configuration. The deployer preserves the
operator `NO_PROXY`, adds `127.0.0.1`, `localhost`, `pgvector`, `redis`, `neo4j` and `web`, and
performs the host health probe with an explicit proxy bypass. These values are not injected into
the running web service.

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

`doctor` is read-only and collect-all. One invocation reports `WEB_INTRANET`, `DATAHUB`,
`QUALITY_READ`, `CHAT`, `EMBEDDING`, `RERANKER`, `MCL_DISCOVERY`, `AIRFLOW`, and `MINIO` as
`READY`, `DEFERRED`, `FAILED`, or `BLOCKED_BY_DEPENDENCY`, with only a bounded classification on a
failure. Independent LLM, Kafka, Airflow, and MinIO checks continue after another stage fails.
`QUALITY_READ` may be blocked by an unavailable DataHub transport; the MCL Kafka cluster/topic
checks still run independently before DataHub provider-version or Registry dependencies where
possible. Doctor exits nonzero when a required stage failed but never writes Product state,
checkpoints, receipts, secrets, or accepted markers. Deploy remains fail-closed before its first
persistent mutation.

Doctor does not assume that the candidate image already exists, but it does require the promoted
archive named by `release.json`. It verifies the archive checksum and bounded OCI/Docker contents.
If the exact tag is absent, doctor loads that archive; if present, it reuses the tag only after the
exact manifest, platform and OCI revision pass inspection. Doctor never builds or pulls a fallback
image. Loading the approved archive does not start PostgreSQL, Neo4j, Redis or the persistent Web
service and does not write Product state. Doctor collect-all and deploy fail-fast provider checks
both run the verified image through
one hardened disposable `docker run --rm` executor with the same mode-0600 canonical effective
environment, linux/amd64 platform, non-root user, read-only root filesystem, dropped capabilities,
no-new-privileges policy, and optional read-only runtime CA bind. Only the preflight mode differs.
Neither path uses the Web Compose service or creates Compose volumes/state-service dependencies.

Image preparation failures are separately typed for missing/unreadable artifacts, checksum or
archive-contract mismatch, load failure, missing image, image/tag mismatch, manifest mismatch,
platform mismatch and revision mismatch. Ephemeral container
creation and the pinned Node/module launch are respectively
`PREP_DOCTOR_PREFLIGHT_CONTAINER_START_FAILED` and
`PREP_DOCTOR_PREFLIGHT_NODE_START_FAILED`. Only a successfully launched child that emits no valid
matrix contract is `PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID`; raw Docker/provider stderr is
not printed.

Kafka bootstrap TCP reachability alone is not readiness. MCL discovery uses bounded connection,
request, and retry budgets. Failure while resolving cluster metadata after bootstrap—including an
advertised broker address that PREP cannot reach—is typed as the Kafka cluster/metadata stage;
topic, Registry, subject, schema, and provider-version failures remain separate. DataRiver neither
rewrites DataHub `advertised.listeners` nor deploys another Kafka.

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

Accepted running/stopped fast paths additionally require a matching durable `ACCEPTED` attempt,
accepted marker, canonical physical volume set, target ownership fingerprint, and compatible
Product/Handoff ancestry. Marker presence alone is never ownership proof. Foreign/copied/stale,
partial, fingerprint-mismatched, or lineage-incompatible accepted state fails closed without
fresh-install fallback.

Before Product-owned PostgreSQL DDL, PREP fingerprints only the bounded `public.poc_*` tables,
columns/types/defaults, constraints, indexes, triggers, functions and enum/domain types. Unrelated
schemas, extensions, tables and rows are excluded. Only fresh, exact current, or one explicitly
listed older migratable fingerprint proceeds; partial, malformed, receipt-mismatched or newer
Product-owned state stops before mutation.

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

The exact promoted image performs bounded DataHub, Chat, Embedding and Reranker requests before the
attempt receipt and any Product-owned durable mutation. It also performs a read-only DataHub
Assertion query, MCL source discovery, and optional existing Airflow/MinIO readiness. These checks
use configured exact endpoints rather than assuming `/health` or `/models`.

The tracked Product and Chat preflight share the fixed `POC_LLM_TIMEOUT_MS=120000` per-call policy.
It is derived from `env-contract.json`, not requested from the PREP operator. The authenticated
smoke retains a 300,000 ms outer HTTP envelope so the bounded AUTO classifier and GENERAL composer
can complete sequentially without overriding either Product call deadline. Product timeout,
authentication, connectivity, provider HTTP and response-contract failures remain distinct
sanitized smoke classifications; a GENERAL route/evidence mismatch remains
`PREP_SMOKE_GENERAL_ROUTE_FAILED`.

Authenticated smoke emits stage progress and bounded heartbeats instead of hiding a long captured
subprocess. Host health always uses loopback transport at `http://127.0.0.1:39083`, while login,
logout, and GENERAL Chat send the exact canonical `POC_PUBLIC_ORIGIN` as their HTTP `Origin` header.
The loopback transport is never accepted as an alternate authentication origin. Login failures
distinguish canonical-origin rejection (`PREP_SMOKE_ADMIN_ORIGIN_FAILED`) from actual credential
rejection (`PREP_SMOKE_ADMIN_AUTH_FAILED`). Other failures are classified as DataHub
connectivity/auth, K9/semantic readiness, or GENERAL provider/route. Sanitized failure metadata is
stored in ignored `runtime/prep39083/smoke-failure.json`; it contains no URL, credential, token or
response body and is superseded by the next successful smoke.

The DataHub stage also performs a read-only GlossaryTerm acceptance check. An optional
`PREP_GLOSSARY_TERM_URN` in `.env.prep` selects one exact canonical Term; when blank, the Product
deterministically discovers one current `GLOSSARY_TERM` from the configured target and verifies the
same exact URN through `entityExists`, `GlossaryTerm.exists`, current status, entity type, and basic
metadata read-back. It never falls back to a sample business term and never creates, mutates, or
deletes target metadata. An empty target glossary fails explicitly. Provider and contract failures
preserve only bounded substage, operation, reason, and nested code diagnostics; response bodies,
names, descriptions, credentials, and tokens are not retained.

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
