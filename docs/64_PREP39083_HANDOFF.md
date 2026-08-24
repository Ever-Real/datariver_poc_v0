# PREP39083 source build and acceptance

## Fixed release identity and boundary

This runbook prepares, but does not claim, the first WSL/Linux amd64 runtime acceptance for the
read-only Cytoscape refinement. The accepted runtime source is:

```text
Product  179093643f4cfa2dd808c0c27240f7f49f68063c
Evidence 192f26863e89636d33f9d50c7346a92d7dae2aba
Platform linux/amd64
Port     39083
Project  datariver-prep39083
```

Commits after Evidence may contain only handoff scripts, documentation, examples and tests. The
release tool fails if any `frontend` or canonical POC Docker/Compose/runtime-init input differs from
the Product tree. PREP builds the Product on Linux amd64; Mac images are never transferred.

The POC owns its pgvector, Neo4j and Redis services. DataHub, Airflow, MinIO and the three
OpenAI-compatible inference stages are external endpoints and are not added to Compose. The
accepted POC authentication plane is local human credentials plus opaque server sessions. It does
not consume OIDC settings; an environment that mandates OIDC must use the full platform deployment
profile instead of inventing POC variables.

## 1. Fetch, platform and source gate

Run from a WSL Linux-filesystem checkout, not `/mnt/c`:

```bash
set -eu
git fetch origin dev
git checkout dev
git pull --ff-only origin dev

PRODUCT_SHA=179093643f4cfa2dd808c0c27240f7f49f68063c
EVIDENCE_SHA=192f26863e89636d33f9d50c7346a92d7dae2aba
test "$(uname -m)" = x86_64
test "$(docker info --format '{{.Architecture}}')" = x86_64 \
  || test "$(docker info --format '{{.Architecture}}')" = amd64
docker compose version
python3 scripts/prep39083_release.py source-check \
  --product-sha "$PRODUCT_SHA" --evidence-sha "$EVIDENCE_SHA"
```

The current remote is the canonical repository configured on this checkout. Do not rewrite its URL
or credentials in a runbook. A failed ancestry/runtime-input check is a stop condition.

## 2. Local configuration and secret hygiene

```bash
set -eu
install -m 0600 deploy/prep39083/.env.prep.example deploy/prep39083/.env.prep
editor deploy/prep39083/.env.prep
```

Replace every `CHANGE_ME` value. Set both `POC_SOURCE_COMMIT` and `POC_IMAGE_TAG` to the full Product
SHA. Keep `POC_DATAHUB_ALLOW_NO_TOKEN=false`, Linux/amd64, port 39083 and the project/network names.
Use target-routable DNS or HTTPS endpoints; `host.docker.internal`, Mac paths and local Ollama model
IDs are invalid here. Do not put credentials in shell arguments, Git, Docker build arguments or an
Evidence file.

The ignored `.env.prep` is the live target-owned secret/configuration boundary. Before continuing:

```bash
set -eu
test "$(stat -c '%a' deploy/prep39083/.env.prep)" = 600
test -z "$(grep -n 'CHANGE_ME' deploy/prep39083/.env.prep || true)"
docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep \
  --file deploy/poc/docker-compose.poc.yaml config --quiet
```

Provider certificates, DNS routes and authorization are environment-owned. Probe them without
printing bearer tokens or passwords. The authenticated application smoke below is the final
DataHub/LLM connectivity proof; Airflow/MinIO commands should use their own approved service probes.

## 3. Side-by-side build and start

Record the current 39080 containers first. Never stop or recreate them:

```bash
set -eu
docker ps --filter publish=39080 --format '{{.ID}} {{.Names}}' > /tmp/datariver-39080-before.txt

docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep \
  --file deploy/poc/docker-compose.poc.yaml \
  build --pull=false web

IMAGE_REF="datariver-poc:$PRODUCT_SHA"
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE_REF")" = linux/amd64
test "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE_REF")" = "$PRODUCT_SHA"

docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep \
  --file deploy/poc/docker-compose.poc.yaml \
  up -d --no-build --wait

docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep \
  --file deploy/poc/docker-compose.poc.yaml ps
curl --fail --silent --show-error http://127.0.0.1:39083/healthz
docker ps --filter publish=39080 --format '{{.ID}} {{.Names}}' > /tmp/datariver-39080-after.txt
cmp /tmp/datariver-39080-before.txt /tmp/datariver-39080-after.txt
```

The project name, network name, diagnostic host ports and Compose-named volumes differ from the
39080 project. Do not use `docker compose down -v`; volumes contain PostgreSQL/pgvector state,
managed graph pointers, scheduler ownership/generation state and Neo4j projections.

## 4. Bootstrap one PREP operator safely

The bootstrap command is an explicit local-auth action, not an OIDC substitute. Use a unique real
PREP subject and do not reuse a DEV credential. Create a mode-0600 password file outside Git and
delete it after acceptance:

```bash
set -eu
umask 077
read -r -s -p 'PREP acceptance password: ' PREP_PASSWORD; echo
printf '%s\n' "$PREP_PASSWORD" > /tmp/datariver-prep39083.password
unset PREP_PASSWORD

docker run --rm --user "$(id -u):$(id -g)" \
  --network datariver-prep39083-services \
  --env-file deploy/prep39083/.env.prep \
  -e POC_POSTGRES_HOST=pgvector -e POC_POSTGRES_PORT=5432 \
  -e POC_REDIS_URL=redis://redis:6379/0 \
  --mount type=bind,src=/tmp/datariver-prep39083.password,dst=/run/prep.password,readonly \
  "datariver-poc:$PRODUCT_SHA" \
  node poc-bootstrap-local-user.mjs --env-file /dev/null \
  --password-file /run/prep.password \
  --subject-id prep39083-acceptance-admin --username prep39083-acceptance-admin \
  --role admin --set-active-subject
```

If a durable approved PREP administrator already exists, do not create a duplicate. Use that
identity and record only its non-secret subject identifier.

## 5. Smoke and authenticated browser acceptance

```bash
set -eu
mkdir -p runtime/prep39083
node scripts/smoke_prep39083.mjs \
  --origin http://127.0.0.1:39083 \
  --username prep39083-acceptance-admin \
  --password-file /tmp/datariver-prep39083.password \
  --output runtime/prep39083/smoke.json
```

The smoke requires HTTP 200, login, current DataHub access, both READY managed graphs, DAILY
refresh, READY semantic index and one GENERAL response with zero internal retrieval. Also inspect
the running container rather than trusting the tag:

```bash
set -eu
WEB_ID="$(docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep --file deploy/poc/docker-compose.poc.yaml ps -q web)"
test "$(docker inspect --format '{{.State.Health.Status}}' "$WEB_ID")" = healthy
test "$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$WEB_ID")" = "$PRODUCT_SHA"
```

In an authenticated browser at 39083 verify login, Catalog/DataHub, Managed Assets, Default
Lineage READY, Metadata Master READY, semantic-index state and Cytoscape load/hover/drag/expand with
viewport preservation. Hard reload the Knowledge view. Capture no credential in screenshots.

## 6. Separate acceptance suites

Startup never runs the full router suite. After smoke/browser acceptance, run focused routes first:

```bash
node scripts/verify_chat_knowledge_router.mjs \
  --origin http://127.0.0.1:39083 \
  --username prep39083-acceptance-admin \
  --password-file /tmp/datariver-prep39083.password \
  --ids G08,V18,R01 \
  --output runtime/prep39083/router-representative.json
```

Run the curated 60 and Boundary 8 once only when PREP acceptance is scheduled:

```bash
node scripts/verify_chat_knowledge_router.mjs \
  --origin http://127.0.0.1:39083 \
  --username prep39083-acceptance-admin \
  --password-file /tmp/datariver-prep39083.password \
  --output runtime/prep39083/router-60.json
node scripts/verify_chat_knowledge_router.mjs \
  --origin http://127.0.0.1:39083 \
  --username prep39083-acceptance-admin \
  --password-file /tmp/datariver-prep39083.password \
  --suite boundary --output runtime/prep39083/router-boundary.json
```

For MCP/native parity, create a separate mode-0600 file containing the already-provisioned MCP
service token and run `scripts/benchmark_knowledge_adapters.mjs`. Its invalid-token negative is
mandatory. Do not print or commit either credential file.

## 7. Stop and rollback

`stop` preserves every named volume. A rollback means selecting a previously approved exact image
and configuration backup, not resetting data or rebuilding an old tag:

```bash
docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep \
  --file deploy/poc/docker-compose.poc.yaml stop

# After restoring the approved prior env file with its prior exact POC_IMAGE_TAG:
docker compose --project-name datariver-prep39083 \
  --env-file deploy/prep39083/.env.prep \
  --file deploy/poc/docker-compose.poc.yaml up -d --no-build --wait
```

Before schema-affecting updates, back up PostgreSQL and Neo4j. The current POC init SQL is additive
and idempotent but is not a versioned downgrade mechanism. A rollback is compatible only when the
previous image can read the current schema; otherwise restore the pre-update backups as an
explicitly approved recovery action.
