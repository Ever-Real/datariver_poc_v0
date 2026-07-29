# Operations, backup and recovery runbook

## Service ownership and severity

| Signal | Severity trigger | First action |
|---|---|---|
| API canonical readiness | PostgreSQL unavailable for 2 minutes | stop mutations at the edge; preserve liveness |
| outbox lag | oldest unpublished > 5 minutes | inspect Redis delivery/relay; do not edit event rows |
| dead letters | any new row | capture event/error, repair dependency, use an audited replay procedure |
| upload rejection spike | > 5% over 15 minutes | inspect error-code distribution and object-store health |
| DataHub reconcile | active heartbeat > 60 minutes or repeated abandon | pause DAG, validate DataHub contract and restart at offset zero with a new `sync_id` |
| DataHub circuit | `datariver_datahub_circuit_state > 0` or new bulkhead rejections | inspect latency/error outcome, protect API capacity and verify bounded stale projection before recovery |
| catalog cache | sustained `error` outcomes or unexpected hit-rate collapse | verify Redis cache health; correctness must continue through PostgreSQL without extending TTL |
| grant quota denial | sustained 429 | confirm consumer identity/plan before changing limits |

## Local stack control

Bootstrap may be rerun with a replacement DataHub token. It preserves existing database, Redis, S3,
Keycloak and Airflow credentials, migrates legacy Valkey secret filenames when necessary and
regenerates only derived realm files. Do not use bootstrap as a credential-rotation tool.

```bash
./scripts/bootstrap.sh --datahub-token-file /approved-secure-transfer/datahub_token
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml config --quiet
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml ps -a
```

Expected one-shot states are `migrate` and enabled profile init jobs exited with code 0. API, web,
enabled Keycloak/APISIX, PostgreSQL and enabled Airflow components must be healthy. External Redis,
S3/MinIO and feature connectors are checked in their owner deployment and through fixed DataRiver
connection probes; workers, DAG processor and triggerer must remain running when enabled.

For a DNS-less isolated development network, an HTTP/Redis/Bolt endpoint addressed by IP must place
that exact literal in both `SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS` and
`SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS`, followed by an API restart. The latter never
accepts a URL, port, CIDR, wildcard or hostname and does not make the transport encrypted.

Host-port overrides do not change an OIDC issuer. When browser-facing origins change, update `APP_PUBLIC_ORIGIN`, `OIDC_PUBLIC_ORIGIN`, `OIDC_PUBLIC_AUTHORITY` and `OIDC_ISSUER` as one reviewed change and rebuild the affected services.

## Safe restart order

1. Verify the external OIDC, Redis cache/delivery and S3 endpoints required by enabled features.
2. Start PostgreSQL. On an existing volume reconcile packaged runtime roles, run Alembic exactly
   once with the migration identity, then reconcile roles again.
3. Start the API and confirm schema-aware readiness.
4. Start relay/workers only after Redis delivery recovery and the relevant external connectors pass.
5. Start web/gateway and Keycloak/Airflow overlays where applicable; DAGs remain paused until probes pass.
6. Check `/health/ready`, `/capabilities`, `/operations/summary` and protected `/operations/metrics`.

The protected metrics endpoint exposes bounded-label catalog cache access/detail-source counters,
DataHub request outcome/duration/in-flight, queue-rejection and circuit-state signals, plus current
API database-pool checked-in/checked-out/overflow counts and configured base/overflow limits. It does
not expose query text, URNs, workspace IDs, subject IDs, tokens or provider payloads. Cache-server
memory, eviction and keyspace signals still require the external Redis deployment's exporter.

PostgreSQL remains canonical. Never repair a Redis stream by inventing events; recover the relay from unpublished outbox rows.

Outbox/inbox automatic pruning is intentionally disabled. Revision `0006` revokes relay `DELETE` privileges, and `/operations/summary` reports `retention_automation_state=DISABLED_NOT_READY`. Do not manually delete retained rows or grant that privilege back. A future dedicated retention worker may delete only after governed policy activation, immutable export checksum and Object-Lock read-back, Legal Hold evaluation and Maker-Checker approval all succeed.

Chat content persistence is also fail-closed on retention governance. Before enabling Chat for a
workspace, two distinct eligible administrators must propose and approve the policy through the
Admin retention page/API. Confirm `GET /admin/retention/policies/current` returns the intended exact
version and durations. Do not insert an ACTIVE row, alter a session deadline or broaden
`assistant.chat_sessions` privileges manually. With no ACTIVE policy, `/chat/query` returns `409`
after authorization and stores no session/message. Activating a replacement policy append-closes
sessions bound to the prior version; clients start a new session instead of editing history.

## Managed catalog export activation

Catalog export is disabled by default and must remain disabled until all of these controls pass in
the target environment:

1. Provision a dedicated `datariver_export` PostgreSQL login with `NOBYPASSRLS`, no ownership/DDL
   rights and only the reviewed worker grants. Store its generated password in a distinct mounted
   secret referenced by `EXPORT_DATABASE_SECRET_REF`; never reuse API, relay, upload, governance,
   bootstrap or migration credentials.
2. Provision a non-admin object-store identity scoped to multipart write, abort and metadata
   verification on the private `S3_BUCKET_EXPORTS` bucket only. Mount its access and secret keys at
   `S3_EXPORT_ACCESS_KEY_FILE` and `S3_EXPORT_SECRET_KEY_FILE`; do not reuse the API identity.
3. Verify that the API identity can perform only the required artifact metadata read and bounded
   presigned GET operation, while anonymous list/read and worker reads outside the export bucket are
   denied. The bucket must have no public policy or browser credential.
4. Run two-workspace RLS negatives, RESTRICTED exclusion, stale permission/policy/projection
   invalidation, worker kill/lease reclaim, multipart-abort cleanup, size/row limits and object
   metadata/SHA reconciliation. A successful unit test alone is not activation evidence.
5. Set `CATALOG_EXPORT_WORKER_ENABLED=true` for both API feature reporting and the isolated worker,
   start exactly the separately credentialed worker, then verify capability/create/status/download
   with two real human identities. Record the policy generation, projection watermark, object
   receipt and audit correlation IDs without recording URL signatures or credentials.

Emergency disablement sets `CATALOG_EXPORT_WORKER_ENABLED=false` on the API and stops the export
worker. Existing 60-second download URLs are allowed to expire; do not delete request/job/object
evidence during containment. Failed or abandoned multipart uploads are reconciled through the
reviewed storage procedure, never by editing a completed database receipt.

Upload promotion uses validation-attempt-scoped destination keys. If the acceptance transaction
outcome is ambiguous, both quarantine and promoted objects are intentionally preserved. Reconcile
against the committed manifest ID/version/location and full SHA-256 evidence; remove only a proven
unreferenced attempt object through the reviewed incident procedure. Never infer canonical state
from an object-key pattern or delete the quarantine source before the committed receipt is known.

Typed upload preparation has a fenced runtime path, but the shipped Airflow DAG remains paused
until the target identity and provider gates below are accepted. An authorized API request may
create or read a `QUEUED` job only after exact accepted-byte verification. The purpose-bound
registration worker claims one job with database time, parses into an attempt-local bounded spool
and publishes the receipt/candidates in one lease-token-fenced transaction. Operators must never
mark a job `READY`, insert receipts/candidates, reuse the BYPASSRLS upload role or invoke the parser
outside this claim/publish boundary. Queue age while the DAG is paused is expected and is not a
reason to edit evidence.

Production activation requires a reviewed NOBYPASSRLS registration-worker database identity,
workspace/correlation-scoped claim capability, object read limited to verified accepted sources and
no DataHub write credential for BULK preparation. Manual apply separately uses the reviewed scoped
DataHub service principal. The local source implementation and tests do not satisfy those
target-principal gates.

Administrator password fallback is also disabled by default. Before enabling it, query the canonical
membership/subject stores and prove that at least two active, non-service-account,
RESTRICTED-cleared human security administrators have `admin.manage` allowed and not denied. Then
run two distinct real-user password-reauthentication, independent approval, expiry, replay,
revocation and one-time-consume tests. If the count drops below two or the IdP assurance mapping
drifts, disable the feature immediately; do not create a synthetic checker or alter approval rows.

`/health/live` returning 200 with `/health/ready` returning 503 is an intentional diagnostic state.
`SCHEMA_REVISION_MISMATCH` requires the migration identity to apply the packaged sole head;
`DATABASE_READINESS_TIMEOUT` indicates pool lease/query saturation; `DATABASE_UNAVAILABLE` indicates
a bounded connection/query failure. Responses never expose the DSN, observed revision or provider
exception. Do not route traffic to a live-but-not-ready replica.

Web Nginx and APISIX dynamically re-resolve the API service. After replacing the API container, verify direct liveness plus web/gateway `/api/v1/health/ready`; do not restart the UI merely to mask a stale or schema-mismatched upstream.

## Durable Knowledge source analysis

This worker is optional and separately credentialed. Catalog/governance and existing Knowledge reads
remain available when it is disabled; the API rejects a new analysis enqueue before persisting a
queue item. Neo4j is independent and is not an activation prerequisite.

For a new Mac arm64 environment, run the profile bootstrap once, configure/probe the local
Embedding contract, and opt in on the second pass. For a WSL amd64 preparation environment,
configure/probe both private OpenAI-compatible Chat and Embedding contracts before the second pass:

```bash
# Mac arm64
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development \
  --enable-knowledge-source-worker

# WSL linux/amd64
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --datahub-token-file /approved-secure-transfer/datahub_token
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --enable-knowledge-source-worker
```

The second command in each pair intentionally fails until one complete Chat + Embedding pair is
present. WSL/private model reachability, model identity/output conformance and credential handling
are `EXTERNAL_GATE`; do not enable the flag merely to bypass the check. Native Windows PowerShell
uses `.env`: run
`./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'`,
configure/probe the
provider pair, then run `./scripts/bootstrap.ps1 -EnableKnowledgeSourceWorker`.

On a blank PostgreSQL volume, the init hook creates `datariver_knowledge`. On an existing volume the
role must be an unprivileged NOBYPASSRLS LOGIN and must not be a member of any role that it could
adopt with `SET ROLE` before revision `0054`:

```bash
# Choose exactly one and keep it for every following Bash command in this procedure:
DATARIVER_ENV_FILE=.env.mac-development  # Mac
# DATARIVER_ENV_FILE=.env.wsl-preparation  # Linux/WSL
export DATARIVER_ENV_FILE
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml up -d --wait postgres
./scripts/reconcile-postgres-roles.sh
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml run --rm migrate
./scripts/reconcile-postgres-roles.sh
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml run --rm migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current
# Require: 0063 (head)
```

For native Windows use
`./scripts/reconcile-postgres-roles.ps1 -EnvFile .env` before and after the migration. Never reuse
the owner/API password, add BYPASSRLS, stamp the revision or grant DDL to make migration proceed.
Revision `0054` first removes prior direct application-schema privileges and then applies its exact
allowlist. Treat a membership failure as principal contamination: review and explicitly revoke the
unexpected membership rather than weakening the assertion.
Revision `0054` refuses downgrade when the durable source-analysis ledger contains any job. That is
an evidence-preservation gate: preserve backup/logs and use a reviewed forward fix; do not delete
jobs to force downgrade.

Revision `0055` refuses downgrade while a subject-bound V2 consumer grant or atomic
invocation/result/month-usage evidence exists. Revocation does not erase audit evidence. Preserve
the database and use a reviewed forward fix; downgrade is supported only before V2 grant/evidence
creation, where it restores the exact legacy schema and application privileges.

When the selected Mac or WSL profile intentionally uses the optional local MinIO reference, choose
that profile's environment file once. Skip this block for external S3/MinIO:

```bash
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" \
  -f compose.local-connectors.yaml --profile object-storage up -d --wait minio
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" \
  -f compose.yaml --profile object-storage-tools run --rm storage-init
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" \
  -f compose.local-connectors.yaml --profile object-storage \
  run --rm minio-knowledge-identity-init
```

The identity initializer renders the policy against the configured `S3_BUCKET_ACCEPTED`; it grants
only `GetBucketLocation` and accepted-bucket `GetObject`. For external S3/MinIO, the storage owner
creates the bucket and an equivalent non-admin principal, mounts its keys only through
`S3_KNOWLEDGE_ACCESS_KEY_FILE`/`S3_KNOWLEDGE_SECRET_KEY_FILE`, and proves allowed reads plus
anonymous, write, delete and other-bucket denials. External target IAM remains `EXTERNAL_GATE`.

After database and S3 preparation, start and observe only the selected profile:

```bash
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml \
  --profile knowledge-source up -d --wait api knowledge-source-worker
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml \
  logs --since=10m api knowledge-source-worker
```

The worker-owned `knowledge-spool` volume is temporary, not canonical. Inputs are capped at 50 MiB
and 500 pages; the default first 1 MiB stays in memory and the remainder spills to disk. Alert
before free space can no longer cover one maximum source per worker plus temporary/provider
overhead. Keep `KNOWLEDGE_SOURCE_SPOOL_DIRECTORY` absolute, non-root and writable only by the
worker. Do not mount the volume into API/web, back it up as evidence or manually reuse residue.
The worker closes each spool after an attempt; a stopped-process residue may be inspected for
capacity only and cleaned after the corresponding durable job/attempt state is understood.

Operational states are `QUEUED`, `RUNNING`, `RETRY_WAIT`, `CANCEL_REQUESTED`, `SUCCEEDED`, `FAILED`,
`STALE` and `CANCELLED`. `SUPERSEDED` is attempt evidence. A lost worker is not repaired in SQL:
after the database-clock lease expires, a replacement worker supersedes the attempt and retries
within the job's stored limit. A late worker cannot publish with the old token/epoch. Provider,
source, graph/base, ontology, profile or requester-authority drift ends `STALE` and must be
resubmitted after review rather than rebound.

Cancellation is actor-owned and version fenced. Read
`GET /knowledge/graphs/{graph_id}/source-analysis-jobs/{job_id}`, then POST to the same resource's
`/cancel` suffix with the returned positive `version` as `If-Match`, a new 16–200-character
`Idempotency-Key`, and a bounded reason. Queued/retry work cancels immediately; running work records
`CANCEL_REQUESTED`, and only its fenced terminal transaction can become `CANCELLED`. Reuse the same
idempotency key only for the exact same body/version. Never update job/attempt/event/DRAFT rows.

Emergency disablement:

1. Set `KNOWLEDGE_SOURCE_WORKER_ENABLED=false` in the deployment environment.
2. Recreate the API and confirm new enqueue returns the disabled-capability conflict.
3. Stop `knowledge-source-worker`; preserve its logs and PostgreSQL evidence.
4. Cancel intended jobs through the authorized API. A running cancellation remains pending until a
   worker safely observes it; on restart, expired-lease recovery finishes it.
5. Restore only after the DB/S3/Chat/Embedding contracts pass again.

Record a real WSL amd64 run, external S3 IAM negatives, private Chat/Embedding calls, two-user
browser authorization/cancellation, worker kill/reclaim, provider outage, and representative
50-MiB/resource load. These are all `EXTERNAL_GATE`; arm64 source/unit tests and Compose rendering do
not close them.

## Airflow operating boundary

The shipped Airflow `SimpleAuthManager` password file is permitted only on loopback developer hosts. It is pre-created from a mounted secret so no generated password is printed. A production deployment must select and validate its supported enterprise/FAB SSO auth manager before exposure; the Keycloak auth-manager provider must not be adopted without its current stability and compatibility review.

The Airflow API has a 90-second startup grace because provider imports and FastAPI initialization can take more than 50 seconds on modest developer PCs. Diagnose only after that window. Pass conditions are a healthy `/api/v2/monitor/health`, both included DAGs present and paused, and `dags list-import-errors` returning `[]`.

### Registration execution

Keep Manual/BULK DAGs paused until the DataRiver registration-worker client has a short-lived
client-credentials token, MinIO/S3 bucket probes pass and the scoped DataHub service principal can
read and write only the five reviewed aspects. Airflow receives neither storage nor DataHub
credentials. Start with one worker call at a time and inspect DataRiver status/report APIs; never
edit a submission, attempt, candidate or receipt row to force completion.

Each Airflow task invocation supplies one stable `X-Run-Id` and an ordinal `X-Run-Call` (Manual
1..10, BULK 1..8). DataRiver stores and replays the committed response for the same workspace,
operation and run-call for 24 hours, so a lost HTTP response does not perform a second effect. A
different DAG retry must reuse the same identifiers. Authentication and authorization still run
before replay. A process loss before the result is committed is governed by the canonical
submission/job lease, idempotent provider read-back and recovery evidence; do not synthesize an
Airflow success.

Before Alembic `0046`, stop registration worker calls and resolve every Manual row in `QUEUED` or
`APPLYING`.
On a blank host, run the repository database-role initializer before Alembic. The earlier `0025`
revision also requires the mounted `POSTGRES_EXPORT_PASSWORD_FILE`; omitting either prerequisite is
a bootstrap failure, not permission to stamp past the migration.

A healthy Manual execution has five ordered aspect reports with
`expected_hash == observed_hash`. A provider 2xx without read-back is not healthy. Retryable work
returns to `QUEUED` with database-owned `next_attempt_at`; attempts stop at 20. Treat an unreferenced
conditional-write object after an integrity failure as an incident/reconciliation item. Do not
unconditionally delete the key because a concurrent writer may own the current version.
`FAILED_BEFORE_WRITE`, `WRITE_REJECTED`, `READBACK_FAILED` and `READBACK_MISMATCH` are bounded,
sanitized per-aspect evidence, not permission to mark the attempt successful. Airflow converts a
terminal Manual/BULK business failure to a non-retryable failed task; only OIDC/transport failures
use the configured retry budget. A later empty claim must never rewrite that terminal result as a
successful run.

For a suspected S3/DB receipt split, export a read-only, repeatable-read database manifest through a
credential channel that does not place a password in shell history, then run the read-only
reconciler. Use an exact workspace, configured bucket and
`UPLOAD_METADATA_MANUAL_` prefix. Both sides are capped at 1,000 objects; the scanner defaults to
64 MiB total and refuses classification if either side is truncated. Increase
`--maximum-total-bytes` only within the reviewed 1 GiB hard cap.

```bash
psql "$READ_ONLY_DATABASE_URL" \
  -v workspace_id="$WORKSPACE_ID" \
  -v bucket=datariver-infoschema \
  -v prefix=UPLOAD_METADATA_MANUAL_ \
  -v maximum_references=1000 \
  -f scripts/export_manual_receipt_reconciliation_manifest.sql \
  -o /secure/manual-receipt-db-manifest.json

uv run python scripts/reconcile_manual_receipts.py \
  --database-manifest /secure/manual-receipt-db-manifest.json \
  --endpoint https://s3.example.internal \
  --access-key-file /secure/read-only-s3-access-key \
  --secret-key-file /secure/read-only-s3-secret-key \
  --maximum-objects 1000
```

`DB_REFERENCE_PRESENT` is a full key/metadata/size/SHA match.
`DB_REFERENCE_MISSING`, `DB_REFERENCE_INTEGRITY_MISMATCH`,
`UNREFERENCED_EXACT_METADATA_CANDIDATE` and `MALFORMED_OR_AMBIGUOUS_OBJECT` are incident
classifications only. The utility performs list/HEAD/streamed read and emits JSON; it never updates
PostgreSQL or creates/deletes an object. No output authorizes deletion. Preserve the manifest,
report, release SHA, endpoint identity and operator record for reviewed recovery.

The executable BULK profiles are capped at 16 MiB and 10,000 rows. A `READY` receipt permits only a
typed dataset-description or fixed catalog-metadata preview and one ETag-fenced Change Request.
The V3 profile supports existing table/column description and controlled DOMAIN/TERM/TAG changes;
new assets, raw Aspect names/documents and direct provider writes are not recovery shortcuts.
Each V3 candidate still represents one target and one server-fixed Aspect.
Candidate evidence is staged in a fixed 64 MiB attempt-local spool and replayed in bounded database
batches. `EVIDENCE_TOO_LARGE` means valid source bytes expanded beyond that evidence safety budget;
it is not a source hash mismatch and must not be retried by increasing memory or bypassing the
worker. Preserve the accepted object and failed preparation evidence for contract review.

Before distributing a V3 template, a human security administrator reconciles each vocabulary kind
through `POST /uploads/metadata-vocabulary/sync` with one stable `sync_id`, increasing public
`offset` and a new idempotency key per page. The provider cursor remains server-side. Resume only
at the returned `next_offset`; do not guess a cursor, skip a page or edit local UUID/provider
bindings. `SUPPRESSED_UNVERIFIED_SNAPSHOT` means lookup rows were refreshed but deletion inference
was deliberately disabled. Only `APPLIED` backed by the configured immutable snapshot evidence may
inactivate unseen entries. A stale ACTIVE run older than one hour is abandoned on the next page-zero
reservation with a new `sync_id`; preserve the prior run as evidence. Admin/Data Steward users then
copy only local UUIDs from the bounded no-store lookup UI. Provider URNs never enter templates or
browser storage.

Manual and BULK browser polling stops after 20 checks or 120 seconds and while the tab is hidden.
Use the explicit status-refresh control after inspecting the worker and provider health; do not
increase polling or reload in a loop on low-resource hosts. XLSX ZIP/XML parsing is delegated off
the API event loop and rejects packages above the documented 64 MiB total/32 MiB entry expansion
budgets, 20,000 shared strings or 16 MiB shared-string bytes.

## Credential rotation

1. Identify exactly which services mount the credential and confirm that a dependency supports overlap or coordinated cutover.
2. Create the new value in the environment secret manager or ignored file without printing it to logs.
3. Update the dependency and consumers in the required order, then recreate only affected services.
4. Verify OIDC issuer/audience, database role, Redis/S3/DataHub access and audit continuity as applicable.
5. Revoke the old value and record operator, time, affected identities and validation evidence.

File-based local secrets are readable by container UIDs but protected by owner-only parent directories. They are never committed or copied as Git artifacts.

## Backup procedure

Production automation must encrypt, checksum and immutably retain these artifacts:

1. Record commit, migration revision, image digests, UTC start time and PostgreSQL WAL/LSN.
2. Take a PostgreSQL physical backup or `pg_dump --format=custom` with a role able to read every schema.
3. Snapshot/export the selected external S3 bucket at the same consistency watermark. If snapshots are not atomic, pause new upload completion/promotion while recording the database/object cut line.
4. Export only Keycloak realm configuration needed for recovery; credentials remain in the environment secret manager, not the Git artifact.
5. Store SHA-256 checksums and perform a restore verification. A backup that has not been restored is not accepted evidence.

Redis cache is never backed up. Redis delivery persistence may shorten recovery but is not the
correctness backup because PostgreSQL outbox/inbox is authoritative.

## External connector cutover

Treat an endpoint change as a reviewed migration, not a cosmetic settings edit.

For Valkey-to-Redis cache, stop cache writes briefly if practical, configure the new isolated cache
endpoint and credential, run authenticated PING plus authorization-negative probes, restart API
replicas gradually and allow the cache to warm. Cache contents are deliberately not copied.

For delivery, pause relay and consumers, record unpublished/dead-letter/in-flight counts, allow the
old stream to drain or prove every remaining event is recoverable from PostgreSQL, then point relay
and workers to the new `noeviction` Redis endpoint. Resume relay before consumers, verify inbox
deduplication and lag convergence, and retain the old endpoint until the rollback window closes.

For SeaweedFS-to-MinIO/S3, freeze new upload completion/promotion, inventory every PostgreSQL object
manifest and source object version/size/checksum, copy into private target buckets, and perform full
metadata plus sampled/full-byte checksum read-back according to classification. Validate multipart,
copy, HEAD, presigned CORS, TLS/CA, least-privilege identities and lifecycle policy before changing
`S3_*`. Reconcile every manifest after cutover, resume workers gradually and keep the source
read-only until the rollback window closes. An endpoint-only switch without copied and verified
bytes will orphan existing manifests.

## Isolated restore drill

1. Create an isolated network and empty PostgreSQL/external-S3 recovery targets; block DataHub writes and outbound notifications.
2. Restore PostgreSQL and objects, then verify the recorded migration revision and checksums.
3. Start the API with workers disabled. Check workspace/RLS isolation using two test workspaces and verify manifest-to-object size/SHA samples.
4. Reconcile unpublished outbox, incomplete jobs, active leases and multipart manifests. Expired leases may be reclaimed by normal workers; do not manually mark business completion.
5. Start workers with DataHub write adapter disabled or pointed to a stub. Confirm replay idempotency and no duplicate applied changes.
6. Re-enable DataHub only after read-back hash comparison on a sample. Run a new catalog full reconciliation with a new `sync_id`.
7. Record measured RPO/RTO, row/object counts, exceptions and reviewer approval. Target objectives are RPO <= 5 minutes and RTO <= 60 minutes until deployment-specific evidence supersedes them.

## Dead-letter recovery

Dead-letter rows preserve the original event and error class. Recovery requires an incident/change record, verified dependency repair and a replay tool or SQL procedure reviewed for the exact event schema. Do not clear `dead_lettered_at` in bulk. Replayed consumers remain idempotent through inbox keys and business aggregate guards.

## Security incident containment

- Revoke the IdP client/user and API consumer grant first; do not wait for token expiry.
- Rotate only affected mounted secrets and restart the services that mount them.
- Preserve policy decisions, gateway/request IDs, outbox/job attempts and object manifest evidence.
- If workspace isolation is suspected, stop external traffic and run the cross-workspace RLS test before restoration.
- Never place access tokens, DataHub payloads or confidential Chat content in incident tickets or logs.

## Local policy-revocation probe

With the local semiconductor seed, Keycloak, PostgreSQL and host API running, execute
`uv run python scripts/probe_policy_revocation.py`. The probe keeps one Airflow client-credentials
token while measuring inactive membership, explicit search deny and system/domain scope removal.
It uses the direct API so APISIX request limiting does not contaminate policy-cache timing.

The original membership is restored and compared after every scenario and again on exit. A private,
ignored recovery snapshot exists only while the probe runs. If the process or machine is forcibly
terminated, do not run the probe again; first execute
`uv run python scripts/probe_policy_revocation.py --recover` and verify authorized seed search. The
retained `runtime/policy-probe/last-result.json` contains aggregate timing only; never copy its
temporary recovery snapshot, access token or membership attributes into an incident/evidence store.
