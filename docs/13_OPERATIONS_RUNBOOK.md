# Operations, backup and recovery runbook

## Service ownership and severity

| Signal | Severity trigger | First action |
|---|---|---|
| API canonical readiness | PostgreSQL unavailable for 2 minutes | stop mutations at the edge; preserve liveness |
| outbox lag | oldest unpublished > 5 minutes | inspect Valkey queue/relay; do not edit event rows |
| dead letters | any new row | capture event/error, repair dependency, use an audited replay procedure |
| upload rejection spike | > 5% over 15 minutes | inspect error-code distribution and object-store health |
| DataHub reconcile | active heartbeat > 60 minutes or repeated abandon | pause DAG, validate DataHub contract and restart at offset zero with a new `sync_id` |
| DataHub circuit | `datariver_datahub_circuit_state > 0` or new bulkhead rejections | inspect latency/error outcome, protect API capacity and verify bounded stale projection before recovery |
| catalog cache | sustained `error` outcomes or unexpected hit-rate collapse | verify cache Valkey health; correctness must continue through PostgreSQL without extending TTL |
| grant quota denial | sustained 429 | confirm consumer identity/plan before changing limits |

## Local stack control

Bootstrap may be rerun with a replacement DataHub token. It preserves all existing database, Valkey, S3, Keycloak and Airflow credentials, then regenerates only derived SeaweedFS/realm files. Do not use bootstrap as a credential-rotation tool.

```bash
./scripts/bootstrap.sh '<datahub-token>'
docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml config --quiet
docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml ps -a
```

Expected one-shot states are `migrate`, `storage-init` and `airflow-init` exited with code 0. API, web, Keycloak, APISIX, PostgreSQL, both Valkey instances, SeaweedFS and the Airflow API/scheduler must be healthy; workers, DAG processor and triggerer must remain running.

Host-port overrides do not change an OIDC issuer. When browser-facing origins change, update `APP_PUBLIC_ORIGIN`, `OIDC_PUBLIC_ORIGIN`, `OIDC_PUBLIC_AUTHORITY` and `OIDC_ISSUER` as one reviewed change and rebuild the affected services.

## Safe restart order

1. PostgreSQL and SeaweedFS; verify storage and database health.
2. Run Alembic exactly once with the migration identity.
3. Start Valkey cache/queue; queue AOF recovery must complete before workers.
4. Start API and confirm schema-aware readiness, then relay/workers and web/gateway.
5. Start Keycloak/Airflow overlays where applicable; DAGs remain paused until probes pass.
6. Check `/health/ready`, `/capabilities`, `/operations/summary` and protected `/operations/metrics`.

The protected metrics endpoint exposes bounded-label catalog cache access/detail-source counters and
DataHub request outcome/duration/in-flight, queue-rejection and circuit-state signals. It does not
expose query text, URNs, workspace IDs, tokens or provider payloads. Cache-server memory, eviction
and keyspace signals still require the deployment's Valkey exporter.

PostgreSQL remains canonical. Never repair a Valkey stream by inventing events; recover the relay from unpublished outbox rows.

Outbox/inbox automatic pruning is intentionally disabled. Revision `0006` revokes relay `DELETE` privileges, and `/operations/summary` reports `retention_automation_state=DISABLED_NOT_READY`. Do not manually delete retained rows or grant that privilege back. A future dedicated retention worker may delete only after governed policy activation, immutable export checksum and Object-Lock read-back, Legal Hold evaluation and Maker-Checker approval all succeed.

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

## Airflow operating boundary

The shipped Airflow `SimpleAuthManager` password file is permitted only on loopback developer hosts. It is pre-created from a mounted secret so no generated password is printed. A production deployment must select and validate its supported enterprise/FAB SSO auth manager before exposure; the Keycloak auth-manager provider must not be adopted without its current stability and compatibility review.

The Airflow API has a 90-second startup grace because provider imports and FastAPI initialization can take more than 50 seconds on modest developer PCs. Diagnose only after that window. Pass conditions are a healthy `/api/v2/monitor/health`, both included DAGs present and paused, and `dags list-import-errors` returning `[]`.

## Credential rotation

1. Identify exactly which services mount the credential and confirm that a dependency supports overlap or coordinated cutover.
2. Create the new value in the environment secret manager or ignored file without printing it to logs.
3. Update the dependency and consumers in the required order, then recreate only affected services.
4. Verify OIDC issuer/audience, database role, Valkey/S3/DataHub access and audit continuity as applicable.
5. Revoke the old value and record operator, time, affected identities and validation evidence.

File-based local secrets are readable by container UIDs but protected by owner-only parent directories. They are never committed or copied as Git artifacts.

## Backup procedure

Production automation must encrypt, checksum and immutably retain these artifacts:

1. Record commit, migration revision, image digests, UTC start time and PostgreSQL WAL/LSN.
2. Take a PostgreSQL physical backup or `pg_dump --format=custom` with a role able to read every schema.
3. Snapshot the SeaweedFS data volume at the same consistency watermark. If snapshots are not atomic, pause new upload completion/promotion while recording the database/object cut line.
4. Export only Keycloak realm configuration needed for recovery; credentials remain in the environment secret manager, not the Git artifact.
5. Store SHA-256 checksums and perform a restore verification. A backup that has not been restored is not accepted evidence.

Valkey cache is never backed up. Queue Valkey AOF may shorten recovery but is not the correctness backup because PostgreSQL outbox/inbox is authoritative.

## Isolated restore drill

1. Create an isolated network and empty PostgreSQL/SeaweedFS targets; block DataHub writes and outbound notifications.
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
