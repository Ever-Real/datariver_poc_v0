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
anonymous object GET/HEAD denial, authenticated buckets, a public-endpoint presigned multipart
part with `x-amz-checksum-sha256`, server-side copy,
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

Stop API writers, then allow the relay and every object/delivery worker to drain. Confirm stream
consumer lag and pending counts are zero, stop the relay/workers, and finally confirm unpublished
outbox rows are zero. Keep SeaweedFS online and read-only for rollback.

Export one repeatable-read PostgreSQL evidence manifest. The query includes accepted uploads,
change-request attachments, manual metadata CSVs, knowledge source snapshots and completed catalog
exports. INITIATED uploads are excluded. Immutable retention archives use their separate WORM port
and are deliberately not treated as upload-store objects.

```bash
umask 077
install -d -m 0700 runtime/s3-migration
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec psql -XqAt -U datariver_owner -d datariver' \
  < scripts/export_s3_migration_manifest.sql \
  > runtime/s3-migration/seaweed-to-minio.json
chmod 0600 runtime/s3-migration/seaweed-to-minio.json
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

The database role initializer and every mounted migration secret are prerequisites, not optional
post-migration hardening. In particular, revision `0025` must be able to read the configured
`POSTGRES_EXPORT_PASSWORD_FILE`, and revision `0046` must observe the canonical application roles
before validating grants/RLS. Stop Manual/BULK execution before migration; `0046` deliberately
rejects an unresolved `APPLYING` Manual row or a partially present execution schema.

The Keycloak host-development helper preserves unrelated client attributes and never changes an
existing user's password. Realm-import credentials apply only when the realm is first created;
subsequent password recovery or rotation is an explicit identity-administration operation.

Verify readiness, OIDC login/refresh/logout, catalog paging at 25/50/100, a small upload through
presign/CORS/validation, DataHub read-only behavior and native Ollama chat separately. Keep Airflow,
APISIX, Neo4j and telemetry stopped unless the current Mac test explicitly requires them.

For Registration activation, additionally prove an Admin positive journey, Data Steward
owner-positive/workspace-history-negative journey and inactive/service/ordinary-user negatives.
Then run one exact-commit Manual submission through external Airflow and require all five DataHub
aspect read-backs in its report. Run one typed BULK preparation/candidate preview/CR creation and
verify one immutable candidate binding. Local unit tests, a standalone MinIO conditional-create
probe and an arm64 PostgreSQL migration rehearsal do not close these WSL/external-provider gates.

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

## 7. Final quiesced transfer boundary

Create the final transfer only after the exact cut line: stop API producers; drain relay/workers;
record stream pending/lag and every canonical work/lease counter at zero; stop relay/workers;
capture the same fail-closed evidence again; stop Keycloak; then create a **new** object manifest
and both database dumps without restarting any writer. The earlier SeaweedFS cutover manifest is
evidence, not the final WSL transfer manifest. Use the checked-in helper so this is an executable
gate rather than an operator assertion (add `--include-catalog-export` only when that worker was
enabled):

```bash
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml stop api web
# Keep relay/workers running until this succeeds; failures identify nonzero DB or stream state.
scripts/capture_cutover_state.sh \
  --output-dir runtime/migration/final/pre-stop-cutover-state
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml stop \
  outbox-relay upload-worker upload-validation-worker governance-apply-worker catalog-export-worker
scripts/capture_cutover_state.sh \
  --output-dir runtime/migration/final/cutover-state
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml stop keycloak
```

Dump DataRiver and Keycloak separately without source ownership. Preserve the DataRiver named-role
ACL because the restored Alembic revision will not replay its role grants; omit Keycloak ACL.
Restrictive filesystem permissions must exist before redirection creates any file. Store
basename-only hashes beside all three final artifacts and transfer the directory encrypted:

```bash
umask 077
install -d -m 0700 runtime/migration/final
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec psql -XqAt -U datariver_owner -d datariver' \
  < scripts/export_s3_migration_manifest.sql \
  > runtime/migration/final/object-manifest.json
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec pg_dump -Fc --no-owner -U datariver_owner -d datariver' \
  > runtime/migration/final/datariver.dump
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/keycloak_db_password)" \
   exec pg_dump -Fc --no-owner --no-acl -U keycloak -d keycloak' \
  > runtime/migration/final/keycloak.dump
chmod 0600 runtime/migration/final/{object-manifest.json,datariver.dump,keycloak.dump}
(cd runtime/migration/final && \
  shasum -a 256 datariver.dump keycloak.dump object-manifest.json > SHA256SUMS)
chmod 0600 runtime/migration/final/SHA256SUMS
pg_restore --list runtime/migration/final/datariver.dump >/dev/null
pg_restore --list runtime/migration/final/keycloak.dump >/dev/null
```

The generated realm import is bootstrap-only and is not a substitute for the Keycloak database.
The restored Keycloak database also preserves the hash of the existing `datariver-bootstrap`
credential. Transfer only the source `keycloak_admin_password` through the approved encrypted
secret channel so the post-restore reconciliation helper can authenticate; do not copy the whole
source `secrets/` directory. Target database passwords and connector credentials remain fresh.

## 8. WSL clean import and restore

Clone from the source bundle into a new directory and verify the amd64 artifacts before any
migration. Generate WSL secrets locally; do not reuse Mac deployment credentials unless an approved
credential migration specifically requires it.

```bash
git clone /transfer/datariver-RELEASE/datariver-source.bundle datariver_v1
cd datariver_v1
scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation
scripts/verify_offline_release.sh /transfer/datariver-RELEASE \
  --platform linux/amd64 --load --source-dir "$PWD" --env-file .env.wsl-preparation
```

Set private DNS/TLS endpoints in `.env.wsl-preparation`. Loopback means the current container, so a
remote MinIO/DataHub/LLM must never use `localhost`. For a Windows-host endpoint use the reviewed
`host.docker.internal` bridge only when the service is intentionally host-bound.

The pilot images currently trust only their base-image/public CA bundle. An endpoint signed by a
private CA is therefore a blocked target gate until that CA is mounted and configured for each
selected client container; do not disable TLS verification or copy a CA ad hoc into a running
container. Publicly trusted HTTPS or an explicitly accepted private-network HTTP development
endpoint may be used within the existing adapter policy.

For ordinary Chat through an approved private OpenAI-compatible server, set the exact host in
`INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS`, enable Chat, set its HTTPS `/v1` base URL and model, and
use `file:/run/secrets/intranet_llm_chat_api_key`. Replace that generated placeholder file through
the secret channel. Keep Embedding and `KNOWLEDGE_PIPELINE_ENABLED` disabled unless the separately
required Embedding and Neo4j contracts are selected. A public/SaaS endpoint is outside this
development adapter's accepted boundary.

The wrapper creates the named connector network before a start operation. Choose one Redis branch:

```bash
# Local, separately composed Redis reference
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.local-connectors.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-local-connectors.compose.yaml \
  up -d --wait --no-build --pull never redis-cache redis-delivery

# Or external Redis: do not start the services above; set both private redis:// or rediss:// URLs.
```

The local command assumes `--include-local-connectors` was selected when exporting. On a connected
target that will pull the pinned digest instead, omit the offline connector override and the
`--pull never` flag, then capture the resolved image ID before acceptance. A disconnected target
must not fall back to a registry when the selected archive or override is absent.

Neo4j follows the same explicit choice. For a connected WSL target, set
`NEO4J_ALLOWED_HOSTS=neo4j` and `NEO4J_URI=bolt://neo4j:7687`, then pull/start the digest-pinned
separate connector. For a remote private server, replace `neo4j` in both values with its exact DNS
name; the API rejects a host absent from `NEO4J_ALLOWED_HOSTS`:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  --profile graph -f compose.local-connectors.yaml pull neo4j
scripts/compose.sh --env-file .env.wsl-preparation \
  --profile graph -f compose.local-connectors.yaml up -d --wait neo4j
docker exec datariver-local-connectors-neo4j-1 sh -ec \
  'exec cypher-shell -u neo4j -p "$(cut -d/ -f2- /run/secrets/neo4j_auth)" "RETURN 1"'
```

APISIX is optional edge infrastructure. The current core-only release does not contain it, and the
WSL pilot must not build its mutable upstream base opportunistically. Keep APISIX disabled until a
reviewed `--include-edge` release or a target-approved digest-pinned build is available; direct API
port `8000` remains loopback-only during acceptance. This is a target gate, not permission to use an
unpinned registry image.

Start a new PostgreSQL volume and stop before Keycloak/API. Refuse restore unless both target
databases have zero non-system tables. Restore each dump in one transaction as its target owner.
The offline override is required because an image tar restores the verified tag, not a registry
digest reference:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  up -d --wait --no-build --pull never postgres
(cd /transfer/migration && sha256sum -c SHA256SUMS)
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec psql -XAt -U datariver_owner -d datariver \
   -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('\''r'\'','\''p'\'') AND n.nspname NOT IN ('\''pg_catalog'\'','\''information_schema'\'');"'
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/keycloak_db_password)" \
   exec psql -XAt -U keycloak -d keycloak \
   -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('\''r'\'','\''p'\'') AND n.nspname NOT IN ('\''pg_catalog'\'','\''information_schema'\'');"'
# Both commands above must print exactly 0.
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec pg_restore --single-transaction --exit-on-error --no-owner \
   -U datariver_owner -d datariver' < /transfer/migration/datariver.dump
docker exec -i datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/keycloak_db_password)" \
   exec pg_restore --single-transaction --exit-on-error --no-owner --no-acl \
   -U keycloak -d keycloak' < /transfer/migration/keycloak.dump
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  run --rm --pull never migrate
scripts/compose.sh --env-file .env.wsl-preparation --profile tools \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  run --rm --pull never local-bootstrap
docker exec datariver-next-postgres-1 sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec psql -XAt -U datariver_owner -d datariver \
   -c "SELECT count(*) FROM iam.subjects WHERE id IN ('\''00000000-0000-4000-8000-000000000101'\'', '\''00000000-0000-4000-8000-000000000102'\'') AND issuer = '\''http://localhost:8081/realms/datariver'\'';"'
# The issuer query must print exactly 2 before Keycloak/API starts.
```

If either restore fails, stop there. Preserve its logs and discard only the explicitly verified
fresh target `datariver-next_postgres-data` volume before a clean retry; never retry into a
partially restored database.

Initialize/probe the external MinIO, then copy the final object set from the Mac **MinIO** endpoint
(not SeaweedFS) using `/transfer/migration/object-manifest.json`. Use distinct source and target
credential files, run a dry pass, `--apply`, and a second dry pass requiring
`verified_existing=object_count` and `planned=0`. Do this before API or workers can accept writes.

```bash
scripts/compose.sh --env-file .env.wsl-preparation --profile object-storage-tools \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  run --rm --pull never storage-init

# These endpoint variables contain no credentials. Use private DNS/IP reachable from WSL.
SOURCE_MINIO_ENDPOINT=https://mac-minio.private.example
TARGET_MINIO_ENDPOINT=https://wsl-minio.private.example
uv run python scripts/migrate_s3_objects.py \
  --manifest /transfer/migration/object-manifest.json \
  --source-endpoint "$SOURCE_MINIO_ENDPOINT" \
  --target-endpoint "$TARGET_MINIO_ENDPOINT" \
  --source-access-key-file /transfer/migration/source-minio/access_key \
  --source-secret-key-file /transfer/migration/source-minio/secret_key \
  --target-access-key-file secrets/s3_access_key \
  --target-secret-key-file secrets/s3_secret_key
uv run python scripts/migrate_s3_objects.py \
  --manifest /transfer/migration/object-manifest.json \
  --source-endpoint "$SOURCE_MINIO_ENDPOINT" \
  --target-endpoint "$TARGET_MINIO_ENDPOINT" \
  --source-access-key-file /transfer/migration/source-minio/access_key \
  --source-secret-key-file /transfer/migration/source-minio/secret_key \
  --target-access-key-file secrets/s3_access_key \
  --target-secret-key-file secrets/s3_secret_key \
  --apply
uv run python scripts/migrate_s3_objects.py \
  --manifest /transfer/migration/object-manifest.json \
  --source-endpoint "$SOURCE_MINIO_ENDPOINT" \
  --target-endpoint "$TARGET_MINIO_ENDPOINT" \
  --source-access-key-file /transfer/migration/source-minio/access_key \
  --source-secret-key-file /transfer/migration/source-minio/secret_key \
  --target-access-key-file secrets/s3_access_key \
  --target-secret-key-file secrets/s3_secret_key
```

Start Keycloak alone. Replace the target `keycloak_admin_password` with the securely transferred
source value first, then reconcile the WSL redirect and the target-generated identity/Airflow
client secrets. Supply the target Airflow client secret to the external Airflow owner:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  up -d --wait --no-build --pull never keycloak
DATARIVER_WEB_ORIGIN=http://localhost:8080 scripts/configure_keycloak_host_dev.sh
```

Verify the public issuer is exactly `http://localhost:8081/realms/datariver`, the API uses the
private JWKS URL, and both confidential clients authenticate. Only then start API, web, relay and
selected workers:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  up -d --wait --no-build --pull never \
  api web outbox-relay upload-worker upload-validation-worker governance-apply-worker
```

Redis cache is disposable. Delivery stream state is not copied: the source cut line requires it to
be drained, and canonical PostgreSQL outbox state is checked before the target relay starts.

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
