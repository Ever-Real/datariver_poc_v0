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

### 2.1 Blank-install and iterative-update executables

For a new blank Mac/WSL environment, prefer `scripts/workflow_fresh_setup.py` to executing the
bootstrap and Compose commands in this runbook by hand. For an environment that was completed by
that program, use `scripts/workflow_update_restart.py` after reviewed Git changes. The detailed
commands below remain the diagnostic and migration authority; the fresh workflow is not a database
or object-restore shortcut.

The fresh workflow records only non-secret deployment state under ignored
`runtime/operator-workflow/<profile>.json`. Provider credentials remain under ignored `secrets/`.
The update workflow reads that state, accepts only a clean fast-forward source history, renders
Compose before mutation, stops writers only for a required migration, and recreates only affected
services. External DataHub and MinIO are probed, external Airflow is linked, and external model
activation remains governed separately; none is restarted by DataRiver.

```bash
# Mac blank development topology
./scripts/workflow_fresh_setup.py \
  --profile mac-development \
  --datahub-mode local --redis-mode local \
  --storage-mode local --airflow-mode local

# WSL blank preparation topology; all placeholders must be replaced
RELEASE_DIR="$HOME/workspace/datariver_platform_amd_distribution/restore/datariver-<release-id>"
./scripts/workflow_fresh_setup.py \
  --profile wsl-preparation \
  --release-dir "$RELEASE_DIR" \
  --redis-image-archive /approved-transfer/redis-8.2.6-bookworm-linux-amd64-<release>.tar.gz \
  --datahub-mode external \
  --datahub-base-url http://<actual-datahub-gms-host>:8080 \
  --datahub-token-file /approved-secure-transfer/datahub_token \
  --redis-mode local --storage-mode external \
  --airflow-mode external \
  --airflow-ui-url http://<actual-airflow-ui-host>:8080
```

The WSL source checkout may contain newer documentation, tests and these operator workflow files
than the immutable image release. Any Backend, Frontend, Compose, image-build or runtime
configuration difference is rejected before containers are stopped. Transfer a new release whose
`source-commit.txt` covers that runtime change, retain the old release for rollback, then apply:

```bash
# Mac after committing local development
./scripts/workflow_update_restart.py --profile mac-development

# WSL after the new source and, when runtime changed, new release were transferred
./scripts/workflow_update_restart.py \
  --profile wsl-preparation \
  --git-pull \
  --release-dir "$RELEASE_DIR"
```

Do not use `--assume-yes` until the interactive plan has been accepted on that host at least once.
`--refresh-bootstrap` preserves the existing uppercase Redis/S3/provider/LLM/Neo4j deployment
values while regenerating profile-derived files. Neither executable performs automatic rollback;
use Section 9 with the retained source commit, release, database backup and object evidence.
External Neo4j can be selected with `--graph-mode external`, an exact private Bolt URI on port
`7687`, and a mounted `username/password` credential file. External
OpenAI-compatible Chat/Embedding/Reranker activation is deployment-owned. Set the exact private
endpoint, allowlist, model identity and mounted secret reference in the selected ignored
`.env.<profile>`, run the managed update/restart workflow, and use Admin System Settings only for
the resulting read-only deployment probe. Admin never writes the environment file or hot-reloads
the process.

### 2.2 WSL rapid source-validation topology

The preparation PC may also run the latest checkout directly for rapid `linux/amd64` browser
validation. Keep this separate from `.env.wsl-preparation` and its immutable image acceptance:

```bash
cp -p .env.wsl-preparation .env.wsl-intranet-development
./scripts/bootstrap.sh \
  --env-file .env.wsl-intranet-development \
  --host-development --intranet-source-host \
  --web-public-origin https://<approved-web-dns-name> \
  --oidc-public-origin https://<approved-identity-dns-name>

./scripts/workflow_source_host_infra.py \
  --env-file .env.wsl-intranet-development \
  prepare
```

Stop the containerized API, web and workers before starting source processes; never run duplicate
writers against the same database/Redis. Preserve PostgreSQL, Keycloak and Redis volumes. Run
`scripts/workflow_source_host_infra.py prepare`; it reads the `wsl-preparation` applied state,
verifies the recorded release checksums plus loaded PostgreSQL/Keycloak image IDs, applies the
offline tag override after the digest-pinned base files and recreates both infrastructure services
with loopback publications. A PostgreSQL listing of `5432/tcp` alone does not satisfy source
migration; the required observation is `127.0.0.1:5432->5432/tcp`. Do not manually reconstruct the
release directory or Compose file order.

The two public HTTPS hostnames terminate at the CIDR-restricted Nginx edge generated by
`scripts/render_wsl_intranet_nginx.py`. API, Vite, database, cache and identity upstream ports stay
loopback-only. Mirrored WSL networking is preferred; the NAT portproxy fallback moves client-CIDR
enforcement to the Windows Domain firewall because it does not preserve the original address.
Corporate DNS/CA, Windows/Hyper-V firewall, target WSL, real browser and external provider checks
remain target gates. Use the exact recovery and ingress commands in the root README and the
boundary in [ADR-0051](adr/0051-wsl-intranet-source-host-ingress.md).

## 3. Mac profile and independently operated connectors

Create ignored runtime files once; rerunning bootstrap preserves existing secret files:

```bash
scripts/bootstrap.sh --env-file .env.mac-development --mac-development
scripts/compose.sh --env-file .env.mac-development \
  -f compose.local-connectors.yaml --profile object-storage up -d --wait \
  redis-cache redis-delivery minio
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml --profile object-storage-tools run --rm storage-init
scripts/compose.sh --env-file .env.mac-development \
  -f compose.local-connectors.yaml --profile object-storage \
  run --rm minio-knowledge-identity-init
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

`minio-knowledge-identity-init` renders its read policy from the configured
`S3_BUCKET_ACCEPTED`; it does not assume `datariver-accepted`. It creates a non-admin identity with
only accepted-bucket `GetBucketLocation` and `GetObject`. Record allowed object reads and denied
anonymous, write, delete and other-bucket attempts with that identity. This is local-reference
evidence only; target external S3 IAM remains `EXTERNAL_GATE`.

Durable PDF analysis is optional and does not require Neo4j. To include it in the Mac acceptance,
first configure and probe `LOCAL_OLLAMA_EMBEDDING_*` in `.env.mac-development`, then run:

```bash
scripts/bootstrap.sh --env-file .env.mac-development --mac-development \
  --enable-knowledge-source-worker
scripts/compose.sh --env-file .env.mac-development -f compose.yaml up -d --wait postgres
DATARIVER_ENV_FILE=.env.mac-development scripts/reconcile-postgres-roles.sh
scripts/compose.sh --env-file .env.mac-development -f compose.yaml run --rm migrate
DATARIVER_ENV_FILE=.env.mac-development scripts/reconcile-postgres-roles.sh
scripts/compose.sh --env-file .env.mac-development -f compose.yaml \
  --profile knowledge-source up -d --wait api knowledge-source-worker
```

The bootstrap refuses the opt-in until Chat + Embedding are complete. It creates independent
`datariver_knowledge` and `s3_knowledge_*` credentials; do not substitute the API/owner/general S3
identity. The core remains usable and new PDF enqueue fails closed when the worker flag is false.

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

If durable PDF analysis is selected, require current Alembic head `0055` (the durable job schema was
introduced by `0054`), one job completing as a
typed DRAFT, one version-fenced cancel, and a worker-kill/expired-lease recovery. The worker streams
at most 50 MiB/500 pages, keeps only the configured memory threshold in RAM and spills into its
worker-only `knowledge-spool` volume. Record peak memory and free-volume headroom; spool bytes are
temporary and are not migration artifacts.

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

The API and `knowledge-source-worker` use the same reviewed DataRiver backend image, so the core
bundle contains the worker entry point without a separate mutable image. For both architecture
bundles, require the exact same source commit and record every image platform. An arm64 execution
pass or Mac cross-build is not an amd64/WSL runtime pass.

## 7. Final quiesced transfer boundary

Create the final transfer only after the exact cut line: stop API producers; drain relay/workers;
record stream pending/lag and every canonical work/lease counter at zero; stop relay/workers;
capture the same fail-closed evidence again; stop Keycloak; then create a **new** object manifest
and both database dumps without restarting any writer. The earlier SeaweedFS cutover manifest is
evidence, not the final WSL transfer manifest. Use the checked-in helper so this is an executable
gate rather than an operator assertion (add `--include-catalog-export` only when that worker was
enabled):

If Knowledge source analysis was enabled, stop new enqueue first and require every job terminal, or
cancel it through the actor-owned version-fenced API and let the worker finish. A running lease,
`CANCEL_REQUESTED` row or retry schedule is not a zero-work cut line and must not be repaired by
editing PostgreSQL.

```bash
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml stop api web
# Keep relay/workers running until this succeeds; failures identify nonzero DB or stream state.
scripts/capture_cutover_state.sh \
  --output-dir runtime/migration/final/pre-stop-cutover-state
scripts/compose.sh --env-file .env.mac-development \
  -f compose.yaml -f compose.identity.yaml stop \
  outbox-relay upload-worker upload-validation-worker governance-apply-worker \
  knowledge-source-worker catalog-export-worker
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
scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --datahub-token-file /approved-secure-transfer/datahub_token
scripts/verify_offline_release.sh /transfer/datariver-RELEASE \
  --platform linux/amd64 --load --source-dir "$PWD" --env-file .env.wsl-preparation
```

If the archive was extracted by root or another account, the exporter staging mode can leave the
`amd64` directory non-searchable by the preparation operator. Repair only the immutable release
directory, then rerun verification as the normal Docker operator:

```bash
RELEASE_DIR=/transfer/datariver-RELEASE
sudo chown -R "$(id -un):$(id -gn)" "$RELEASE_DIR"
sudo find "$RELEASE_DIR" -type d -exec chmod 0755 {} +
sudo find "$RELEASE_DIR" -type f -exec chmod 0644 {} +
test -r "$RELEASE_DIR/amd64/datariver-core-amd64.tar"
```

Docker Desktop may record the exporter-side OCI manifest ID while a WSL Docker Engine reports the
loaded single-platform config ID. `already exists` during `docker image load` means a content layer
was reused. When the IDs differ, require the archive checksum, tag, config digest and target
platform to agree instead of deleting images or volumes:

```bash
CORE_TAR="$RELEASE_DIR/amd64/datariver-core-amd64.tar"
(cd "$RELEASE_DIR/amd64" && sha256sum -c datariver-core-amd64.tar.sha256)
CONFIG_PATH=$(
  tar -xOf "$CORE_TAR" manifest.json |
  jq -r '.[] | select((.RepoTags // []) | index("datariver-next-migrate:latest")) | .Config'
)
ARCHIVE_CONFIG_ID="sha256:${CONFIG_PATH##*/}"
LOADED_IMAGE_ID=$(
  docker image inspect datariver-next-migrate:latest --format '{{.Id}}'
)
test "$ARCHIVE_CONFIG_ID" = "$LOADED_IMAGE_ID"
test "$(docker image inspect datariver-next-migrate:latest \
  --format '{{.Os}}/{{.Architecture}}')" = linux/amd64
```

The preparation checkout's ignored `.env.wsl-preparation` is not updated by `git pull`. Rerun
bootstrap after source updates and require `REDIS_CACHE_URL`, `REDIS_DELIVERY_URL`,
`REDIS_CACHE_SECRET_REF` and `REDIS_DELIVERY_SECRET_REF`; do not add new `VALKEY_*` settings.

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
the secret channel. Durable PDF analysis independently requires the matching private Embedding
contract and key; it does **not** require `KNOWLEDGE_PIPELINE_ENABLED` or Neo4j. After configuring
and probing both contracts, rerun the exact preparation bootstrap to opt in:

```bash
scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --enable-knowledge-source-worker
```

A public/SaaS endpoint is outside this development adapter's accepted boundary. Private
OpenAI-compatible Chat/Embedding reachability, response conformance, secret handling and resource
load on WSL are `EXTERNAL_GATE`.

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

If Redis alone was approved and transferred as a separately checksummed Docker archive, load it and
override the digest-qualified online reference with the verified offline tag:

```bash
gzip -dc /transfer/redis-8.2.6-bookworm-linux-amd64-RELEASE.tar.gz |
  docker image load
REDIS_IMAGE=redis:8.2.6-bookworm \
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.local-connectors.yaml \
  up -d --wait --no-build --pull never redis-cache redis-delivery
```

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
scripts/compose.sh --env-file .env.wsl-preparation -f compose.yaml \
  exec -T postgres sh -ec \
  'export PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)"; exec sh /docker-entrypoint-initdb.d/010_roles.sh'
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  run --rm --pull never migrate
scripts/compose.sh --env-file .env.wsl-preparation -f compose.yaml \
  exec -T postgres sh -ec \
  'export PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)"; exec sh /docker-entrypoint-initdb.d/010_roles.sh'
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  run --rm --pull never migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current
# Require exactly: 0055 (head)
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

Require `0055 (head)` after migration. Revision `0054` refuses a missing, privileged, BYPASSRLS or
role-member `datariver_knowledge` principal, so role reconciliation and a reviewed membership
inventory must happen before migration on the restored volume and again afterward. It revokes prior
direct application-schema privileges before applying its exact allowlist. It also refuses downgrade
after any durable analysis job exists; never delete its ledger or stamp around that evidence gate.

Revision `0055` also verifies the complete atomic Sharing schema, RLS, trigger, function and
privilege contract. On the target, exercise invocation through `datariver_app`; direct access to
the ledger/result/month tables must be denied. Real Keycloak service-identity and representative
target lock/load evidence remain explicit acceptance gates.

If either restore fails, stop there. Preserve its logs and discard only the explicitly verified
fresh target `datariver-next_postgres-data` volume before a clean retry; never retry into a
partially restored database.

Initialize/probe the external MinIO, then copy the final object set from the Mac **MinIO** endpoint
(not SeaweedFS) using `/transfer/migration/object-manifest.json`. Use distinct source and target
credential files, run a dry pass, `--apply`, and a second dry pass requiring
`verified_existing=object_count` and `planned=0`. Do this before API or workers can accept writes.
The configured endpoint is the credential-free S3 API origin, never the Console/UI port. For a
Kubernetes NodePort, require evidence that its service `targetPort` is the MinIO API port `9000`;
a NodePort mapped to Console `9001` is not an S3 endpoint. The generated bootstrap credential is
local-only and must be replaced by an externally provisioned access/secret key pair. If the owner
pre-creates the buckets and manages exact-origin CORS outside S3, select
`S3_CORS_MANAGEMENT_MODE=external`; `storage-init` still authenticates and checks every bucket.

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

The WSL external storage owner must also provision the accepted-bucket identity represented by
`S3_KNOWLEDGE_ACCESS_KEY_FILE` and `S3_KNOWLEDGE_SECRET_KEY_FILE`. Give it only
`GetBucketLocation` plus `GetObject` under the exact configured `S3_BUCKET_ACCEPTED`; record
anonymous, write, delete and other-bucket denials. Do not use the storage-initializer/API
credentials in `knowledge-source-worker`. This target IAM proof remains `EXTERNAL_GATE`.

Start Keycloak alone. Replace the target `keycloak_admin_password` with the securely transferred
source value first, then reconcile the WSL redirect and the target-generated identity/Airflow
client secrets. Supply the target Airflow client secret to the external Airflow owner:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  up -d --wait --no-build --pull never keycloak
DATARIVER_WEB_ORIGIN=http://localhost:8080 scripts/configure_keycloak_host_dev.sh
docker inspect --format '{{.State.Health.Status}}' datariver-next-keycloak-1
curl -fsS \
  http://127.0.0.1:8081/realms/datariver/.well-known/openid-configuration \
  >/dev/null
```

Verify the public issuer is exactly `http://localhost:8081/realms/datariver`, the API uses the
private JWKS URL, and both confidential clients authenticate. Keycloak 26 serves health on its
container-internal management port `9000`; only application port `8080` is published as host
`8081`, so host request `http://127.0.0.1:8081/health/ready` returning `404` is not a health failure.
Only then start API, web, relay and selected workers:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  up -d --wait --no-build --pull never \
  api web outbox-relay upload-worker upload-validation-worker governance-apply-worker
```

If durable PDF analysis passed its provider/S3 gates, add it explicitly; otherwise keep the flag
false and leave this profile stopped:

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml \
  -f /transfer/datariver-RELEASE/amd64/offline-core.compose.yaml \
  --profile knowledge-source up -d --wait --no-build --pull never \
  knowledge-source-worker
```

Disablement sets the flag false, recreates the API and stops the worker. It retains queued and
terminal evidence. Use the actor-owned cancel endpoint with the current positive job version in
`If-Match` plus a unique 16–200-character `Idempotency-Key`; never edit lease/job/attempt rows.
After a crash, wait for the database-clock lease to expire and let a restarted worker supersede and
recover the attempt. Keep at least one 50-MiB source per worker plus overhead free in the
worker-only `knowledge-spool` volume.

Redis cache is disposable. Delivery stream state is not copied: the source cut line requires it to
be drained, and canonical PostgreSQL outbox state is checked before the target relay starts.

## 9. WSL acceptance and rollback

Do not route users until all are recorded:

- exact Git commit, checksums, `linux/amd64` image IDs and no-build/no-pull Compose inventory;
- PostgreSQL row counts, Alembic sole head, forced-RLS negative tests and Keycloak OIDC flows;
- Redis cache/delivery policy, MinIO full-byte reconciliation, anonymous denial and CORS/presign;
- catalog pagination/memory, upload, DataHub outage behavior and selected LLM/graph features;
- when selected, durable PDF DRAFT creation, cancellation race, lease reclaim, worker-only spool
  capacity/permissions and core behavior while enqueue is disabled;
- peak RSS/CPU/disk during a representative bounded workload and a restart/restore rehearsal.

The real WSL/browser/OIDC journey, external MinIO/S3 IAM and byte reconciliation, private
OpenAI-compatible Chat/Embedding behavior, amd64 target-daemon execution and representative load
are `EXTERNAL_GATE`. Local Mac tests, cross-builds and artifact-only verification do not close
them.

Rollback stops WSL writers, preserves the failed target and returns traffic to the untouched Mac.
If WSL accepted new writes, do not reverse-copy automatically; reconcile that delta under a new
reviewed migration plan.
