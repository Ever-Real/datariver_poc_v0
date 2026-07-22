# Mac arm64 to WSL amd64 Single-node Pilot runbook

## 1. Boundary and non-goals

This runbook moves one exact DataRiver Git revision from a Docker Desktop Mac development host to
a Windows WSL preparation host. The hosts use different OCI architectures, so Docker volumes and
Mac image tars are never copied to WSL. The release contains one source bundle and separate
`linux/arm64` and `linux/amd64` image bundles.

The preparation host is a **Single-node Pilot**, not HA and not production-ready. PostgreSQL and
Keycloak are DataRiver-owned on that host. Redis, Neo4j and APISIX may be operated with the
separate local connector/edge Compose files or replaced by private external endpoints. MinIO,
DataHub, Airflow, telemetry and the OpenAI-compatible LLM are external contracts on WSL.

Never transfer `.env*` or `secrets/` in the source/image release. Create target values through the
approved secret channel. A database/object migration is a separate encrypted transfer set.

## 2. Required evidence before any write

Record these commands on both hosts:

```bash
docker info --format '{{.OSType}}/{{.Architecture}}'
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
docker compose version
docker system df
git status --short --branch
git rev-parse HEAD
```

Accept only `linux/aarch64` or `linux/arm64` on Mac and `linux/x86_64` or `linux/amd64` on WSL.
Record CPU, RAM and free disk separately. Keep at least twice the release plus database/object
transfer size free during import. Do not continue from a dirty source checkout.

## 3. Mac profile and independently operated connectors

Create ignored runtime files once; rerunning bootstrap preserves existing secret files:

```bash
scripts/bootstrap.sh --env-file .env.mac-development --mac-development
scripts/compose.sh --env-file .env.mac-development \
  -f compose.local-connectors.yaml --profile object-storage up -d --wait \
  redis-cache redis-delivery minio
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml --profile object-storage-tools run --rm storage-init
```

Redis cache must report `appendonly=no` and `maxmemory-policy=allkeys-lfu`. Redis delivery must
report `appendonly=yes`, `appendfsync=everysec` and `maxmemory-policy=noeviction`. MinIO Community
uses the exact cluster-wide `MINIO_API_CORS_ALLOW_ORIGIN` value from `APP_PUBLIC_ORIGIN`; DataRiver
therefore sets `S3_CORS_MANAGEMENT_MODE=external` and does not call unsupported bucket CORS APIs.
The storage initializer still authenticates and reconciles all configured buckets.

Run the self-cleaning development contract probe before accepting the endpoint. It verifies
anonymous denial, authenticated buckets, a presigned PUT, multipart upload, server-side copy,
full-byte SHA-256 read-back and exact-origin CORS:

```bash
uv run python scripts/probe_s3_contract.py \
  --endpoint http://127.0.0.1:9000 \
  --public-endpoint http://127.0.0.1:9000 \
  --access-key-file secrets/s3_access_key \
  --secret-key-file secrets/s3_secret_key \
  --quarantine-bucket datariver-quarantine \
  --accepted-bucket datariver-accepted \
  --allowed-origin http://localhost:38102
```

## 4. SeaweedFS to MinIO object cutover

Stop API writers, relay and every object/delivery worker. Confirm unpublished outbox rows, stream
consumer lag and pending counts are zero. Keep SeaweedFS online and read-only for rollback.

Export one repeatable-read PostgreSQL evidence manifest. The query includes accepted uploads,
change-request attachments, manual metadata CSVs, knowledge source snapshots and completed catalog
exports. INITIATED uploads are excluded. Immutable retention archives use their separate WORM port
and are deliberately not treated as upload-store objects.

```bash
mkdir -p runtime/s3-migration
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec psql -XqAt -U datariver_owner -d datariver' \
  < scripts/export_s3_migration_manifest.sql \
  > runtime/s3-migration/seaweed-to-minio.json
```

The checked-in SQL is streamed to `psql`; it is not mounted into or persisted by the database
container. Never copy/paste a reduced table list. Inspect only the reconciliation counters; all
must be zero/consistent:

```bash
jq '{reference_count,object_count,malformed_count,conflict_count,source_wal_lsn}' \
  runtime/s3-migration/seaweed-to-minio.json
```

Perform a full-byte dry run, then apply. Credentials are read only from files and endpoints cannot
contain credentials. The copier downloads one object at a time, verifies source size/SHA-256,
never overwrites a different target object, uploads only absent objects and fully reads the target
back before success:

```bash
uv run python scripts/migrate_s3_objects.py \
  --manifest runtime/s3-migration/seaweed-to-minio.json \
  --source-endpoint http://127.0.0.1:8333 \
  --target-endpoint http://127.0.0.1:9000 \
  --source-access-key-file secrets/s3_access_key \
  --source-secret-key-file secrets/s3_secret_key

uv run python scripts/migrate_s3_objects.py \
  --manifest runtime/s3-migration/seaweed-to-minio.json \
  --source-endpoint http://127.0.0.1:8333 \
  --target-endpoint http://127.0.0.1:9000 \
  --source-access-key-file secrets/s3_access_key \
  --source-secret-key-file secrets/s3_secret_key \
  --apply
```

Rerun without `--apply`; every object must be `verified_existing`, with `planned=0`. Do not delete
the SeaweedFS volume until the application smoke test and a separately retained backup pass.

## 5. Mac DataRiver cutover

Run migration and identity bootstrap before writers. The optional graph/export processes start only
when their corresponding external service has passed its contract probe.

```bash
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml up -d --build --wait postgres keycloak
DATARIVER_WEB_ORIGIN=http://localhost:38102 scripts/configure_keycloak_host_dev.sh
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml run --rm migrate
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml --profile tools run --rm local-bootstrap
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml up -d --build --wait \
  api web outbox-relay upload-worker upload-validation-worker governance-apply-worker
```

Verify readiness, OIDC login/refresh/logout, catalog paging at 25/50/100, a small upload through
presign/CORS/validation, DataHub read-only behavior and native Ollama chat separately. Keep Airflow,
APISIX, Neo4j and telemetry stopped unless the current Mac test explicitly requires them.

## 6. Freeze and export exact source/images

Commit and verify the source first. Generate each architecture directory from the same clean
commit. The Mac may cross-build amd64; WSL must still perform target-daemon verification.

For a core-only release:

```bash
scripts/export_offline_images.sh --platform linux/arm64 --build-datariver
scripts/export_offline_images.sh --platform linux/amd64 --build-datariver
```

Redis/MinIO, Neo4j and APISIX are not part of the core tar. If redistribution of the exact
distributions has been reviewed, include them on the **first and only** export for each platform:

```bash
scripts/export_offline_images.sh --platform linux/arm64 --build-datariver \
  --include-local-connectors --accept-local-connector-license-review \
  --include-graph --include-edge
scripts/export_offline_images.sh --platform linux/amd64 --build-datariver \
  --include-local-connectors --accept-local-connector-license-review \
  --include-graph --include-edge
```

Platform directories are immutable; options cannot be appended later. Prefer pulling the exact
pinned connector digests directly on a connected WSL host. Never interpret an artifact-only check
on Mac as WSL import evidence.

## 7. PostgreSQL and Keycloak logical transfer

After quiescing writers, create custom-format dumps inside the PostgreSQL container. Dump DataRiver
and Keycloak separately with no source ownership or ACL. Store hashes beside them and transfer the
directory encrypted:

```bash
mkdir -p runtime/migration
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec pg_dump -Fc --no-owner -U datariver_owner -d datariver' \
  > runtime/migration/datariver.dump
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/keycloak_db_password)" \
   exec pg_dump -Fc --no-owner --no-acl -U keycloak -d keycloak' \
  > runtime/migration/keycloak.dump
shasum -a 256 runtime/migration/*.dump > runtime/migration/SHA256SUMS
```

Pause Keycloak during its final dump if preserving live sessions/identity changes is required.
The generated realm import is bootstrap-only and is not a substitute for the Keycloak database.

## 8. WSL clean import and restore

Clone from the source bundle into a new directory and verify the amd64 artifacts before any
migration. Generate WSL secrets locally; do not reuse Mac deployment credentials unless an approved
credential migration specifically requires it.

```bash
git clone datariver-source.bundle datariver_v1
cd datariver_v1
scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation
scripts/verify_offline_release.sh /transfer/datariver-RELEASE \
  --platform linux/amd64 --load --source-dir "$PWD" --env-file .env.wsl-preparation
```

Set private DNS/TLS endpoints in `.env.wsl-preparation`. Loopback means the current container, so a
remote MinIO/DataHub/LLM must never use `localhost`. For a Windows-host endpoint use the reviewed
`host.docker.internal` bridge only when the service is intentionally host-bound.

Start a new PostgreSQL volume and stop before Keycloak/API. Refuse restore unless both target
databases are empty. Restore as their target owners, run Alembic, then start identity and core:

```bash
scripts/compose.sh --env-file .env.wsl-preparation -f compose.yaml up -d --wait postgres
shasum -a 256 -c /transfer/migration/SHA256SUMS
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec pg_restore --exit-on-error --no-owner \
   -U datariver_owner -d datariver' < /transfer/migration/datariver.dump
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/keycloak_db_password)" \
   exec pg_restore --exit-on-error --no-owner --no-acl \
   -U keycloak -d keycloak' < /transfer/migration/keycloak.dump
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml run --rm migrate
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml up -d --wait keycloak api web
```

Restore S3 objects to the external MinIO with the same manifest/copy tool, using separate target
credential files when credentials differ. Redis cache is disposable. Delivery stream state is not
silently copied: cut over only after the source stream is drained, then let the outbox relay replay
any still-unpublished canonical PostgreSQL events.

## 9. WSL acceptance and rollback

Do not route users until all are recorded:

- exact Git commit, checksums, `linux/amd64` image IDs and no-build/no-pull Compose inventory;
- PostgreSQL row counts, Alembic sole head, forced-RLS negative tests and Keycloak OIDC flows;
- Redis cache/delivery policy, MinIO full-byte reconciliation, anonymous denial and CORS/presign;
- catalog pagination/memory, upload, DataHub outage behavior and selected LLM/graph features;
- peak RSS/CPU/disk during a representative bounded workload and a restart/restore rehearsal.

Rollback stops WSL writers, preserves the failed target and returns traffic to the untouched Mac.
If WSL accepted new writes, do not reverse-copy automatically; reconcile that delta under a new
reviewed migration plan.
