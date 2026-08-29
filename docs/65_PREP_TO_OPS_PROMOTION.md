# PREP39083 to OPS image promotion

## Promotion invariant

OPS receives the exact Linux/amd64 images already running during PREP acceptance. It never rebuilds
or pulls them. Operator/runtime environment files, credentials, PostgreSQL/Neo4j data and scheduler state are not in
the release archive. DataHub, Airflow, MinIO and OpenAI-compatible providers remain external.

The Web image accepted on PREP is itself the checksum-pinned Product archive produced once on the
DEV release host and named by the PREP Handoff. PREP verifies, loads and starts that artifact with
no build/pull fallback; this later PREP→OPS export therefore preserves the same build lineage.

An intermediate DEV archive is never OPS promotion authority. If runtime inputs
changed after its Product checkpoint, it cannot be used for a descendant PREP
or OPS release; a fresh exact artifact is required.

## 1. Export only after PREP acceptance

On PREP, keep the accepted `datariver-prep39083` containers running and the checkout clean. The
normal export path reads its exact identity from the tracked release contract:

```bash
./scripts/prep39083 export
```

`export` does not build or restart anything. It requires native Linux amd64, one running healthy
container per Compose service, an exact Product OCI label, immutable tag-to-running-image matches,
Product/Evidence ancestry and no runtime-input drift. It saves those four exact image references
and writes a manifest containing Product, Evidence, handoff commit, image IDs, architecture, image
build timestamp, Compose revision, configuration-schema revision, the canonical PostgreSQL init
tree checksum and `images.tar` SHA-256. The init tree is bundled because a new OPS pgvector volume
must execute the same schema bootstrap referenced by the canonical Compose file.

Copy only the generated `.tar.gz` and its `.sha256` sidecar to approved transfer media. Do not copy
`.env.prep`, passwords, MCP tokens, runtime Evidence containing credentials, or database volumes.

## 2. Artifact-only verification on OPS

```bash
set -eu
sha256sum -c datariver-prep39083-*-amd64.tar.gz.sha256
mkdir datariver-prep39083-release
tar -xzf datariver-prep39083-*-amd64.tar.gz -C datariver-prep39083-release
cd datariver-prep39083-release
python3 prep39083_release.py verify \
  --bundle ../datariver-prep39083-*-amd64.tar.gz \
  --checksum-file ../datariver-prep39083-*-amd64.tar.gz.sha256
```

The verifier rejects unsafe archive paths, unexpected files, an invalid manifest/platform, a bad
bundle checksum, a bad `images.tar` checksum or an incomplete image inventory. It does not load an
image or mutate OPS.

## 3. Load, configure and prove image identity

Loading images and starting services are OPS-authorized actions and are not performed by DEV:

```bash
set -eu
docker load --input images.tar
install -m 0600 .env.ops.example .env.ops
editor .env.ops
test -z "$(grep -n 'CHANGE_ME' .env.ops || true)"

PRODUCT_SHA="$(python3 -c 'import json; print(json.load(open("release-manifest.json"))["product_sha"])')"
EVIDENCE_SHA="$(python3 -c 'import json; print(json.load(open("release-manifest.json"))["evidence_sha"])')"
sed -i "s/^POC_IMAGE_TAG=.*/POC_IMAGE_TAG=$PRODUCT_SHA/" .env.ops
sed -i "s/^POC_SOURCE_COMMIT=.*/POC_SOURCE_COMMIT=$PRODUCT_SHA/" .env.ops

docker compose --project-name datariver-ops39083 \
  --env-file .env.ops \
  --file docker-compose.poc.yaml \
  --file docker-compose.ops.yaml config --quiet
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "datariver-poc:$PRODUCT_SHA")" = linux/amd64
test "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "datariver-poc:$PRODUCT_SHA")" = "$PRODUCT_SHA"
```

Compare every loaded image ID with `release-manifest.json` before startup. A missing or different ID
is a hard stop; do not substitute `latest`, pull, retag another image or build on OPS.

## 4. No-build start and smoke

```bash
set -eu
docker compose --project-name datariver-ops39083 \
  --env-file .env.ops \
  --file docker-compose.poc.yaml \
  --file docker-compose.ops.yaml \
  up -d --no-build --wait

docker compose --project-name datariver-ops39083 \
  --env-file .env.ops \
  --file docker-compose.poc.yaml \
  --file docker-compose.ops.yaml ps
curl --fail --silent --show-error http://127.0.0.1:39083/healthz
```

The OPS override removes the canonical `build:` stanza and sets `pull_policy: never` for all four
services; `--no-build` remains mandatory defense in depth. Bootstrap an OPS-owned local user only if
one does not already exist, using the bundled `poc-prep-bootstrap.mjs` through `docker compose run`
with the OPS Compose environment and a short-lived mode-0600 password-file mount. Never recreate a
raw `docker run` path with separately typed PostgreSQL variables. Run `smoke_prep39083.mjs` with an
OPS-owned mode-0600 password file. Keep the request transport on loopback, but pass the exact OPS
`POC_PUBLIC_ORIGIN` as the smoke request origin for login, logout, and Chat CSRF validation. Then
perform authenticated browser login, managed-graph/Cytoscape hard reload and representative
GENERAL/VECTOR/GRAPH checks.

## 5. Persistence and rollback

Never use `docker compose down -v`, `docker volume rm`, Neo4j namespace deletion, semantic-generation
reset or scheduler-pointer reset as deployment or rollback. PostgreSQL/pgvector owns credentials,
authorization, graph manifests/pointers, semantic generation ownership and scheduler state. Neo4j
owns the active projections. Redis is a cache, but its absence does not authorize deleting the
durable stores.

Before a schema-affecting release, capture and verify PostgreSQL and Neo4j backups. Rollback selects
the previous approved image bundle and its environment backup, uses the same `--no-build` Compose
path and reruns smoke. Restore persistent data only through an independently approved recovery plan
when schema compatibility requires it.
