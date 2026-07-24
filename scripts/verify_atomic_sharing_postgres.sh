#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
container_name="${DATARIVER_SHARING_VERIFY_CONTAINER:-datariver-sharing-atomic-verify}"
host_port="${DATARIVER_SHARING_VERIFY_PORT:-55470}"
keep_container="${DATARIVER_SHARING_VERIFY_KEEP:-0}"

if [[ "${DATARIVER_SHARING_VERIFY_CONFIRM:-}" != "1" ]]; then
  echo "Set DATARIVER_SHARING_VERIFY_CONFIRM=1 to create the isolated verification container." >&2
  exit 2
fi
if [[ ! "$container_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,62}$ ]]; then
  echo "DATARIVER_SHARING_VERIFY_CONTAINER is invalid." >&2
  exit 2
fi
if [[ ! "$host_port" =~ ^[0-9]{4,5}$ ]] || ((host_port < 1024 || host_port > 65535)); then
  echo "DATARIVER_SHARING_VERIFY_PORT must be an unprivileged TCP port." >&2
  exit 2
fi
if docker inspect "$container_name" >/dev/null 2>&1; then
  echo "Refusing to reuse or delete existing container: $container_name" >&2
  exit 2
fi
for executable in docker openssl shasum; do
  command -v "$executable" >/dev/null || {
    echo "Required executable is unavailable: $executable" >&2
    exit 2
  }
done
for executable in "$repo_root/.venv/bin/alembic" "$repo_root/.venv/bin/pytest" \
  "$repo_root/.venv/bin/python"; do
  [[ -x "$executable" ]] || {
    echo "Locked project executable is unavailable: $executable" >&2
    exit 2
  }
done

secret_dir="$(mktemp -d "${TMPDIR:-/tmp}/datariver-sharing-verify.XXXXXX")"
chmod 700 "$secret_dir"
owner_secret="$secret_dir/postgres-owner.secret"
app_secret="$secret_dir/postgres-app.secret"
knowledge_secret="$secret_dir/postgres-knowledge.secret"
openssl rand -hex 24 >"$owner_secret"
openssl rand -hex 24 >"$app_secret"
openssl rand -hex 24 >"$knowledge_secret"
chmod 600 "$owner_secret" "$app_secret" "$knowledge_secret"

cleanup() {
  if [[ "$keep_container" != "1" ]]; then
    docker rm -f "$container_name" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$secret_dir"
}
trap cleanup EXIT

docker run -d --name "$container_name" \
  -p "127.0.0.1:${host_port}:5432" \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres-owner \
  -v "$owner_secret:/run/secrets/postgres-owner:ro" \
  postgres:17.10-bookworm >/dev/null

for _attempt in {1..30}; do
  if docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container_name" pg_isready -U postgres -d postgres >/dev/null

app_password="$(tr -d '\r\n' <"$app_secret")"
knowledge_password="$(tr -d '\r\n' <"$knowledge_secret")"
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d postgres <<SQL
CREATE ROLE datariver_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD '${app_password}';
CREATE ROLE datariver_knowledge LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  PASSWORD '${knowledge_password}';
CREATE ROLE datariver_archive NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE datariver_bootstrap NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE datariver_export NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE datariver_governance NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE datariver_relay NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE datariver_retention_scheduler NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE datariver_upload NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
SQL

owner_url() {
  printf 'postgresql+asyncpg://postgres@127.0.0.1:%s/%s' "$host_port" "$1"
}
app_url() {
  printf 'postgresql+asyncpg://datariver_app@127.0.0.1:%s/%s' "$host_port" "$1"
}
create_database() {
  docker exec -i "$container_name" createdb -U postgres --template=template0 "$1"
}
alembic_for() {
  local database_name="$1"
  shift
  MIGRATION_DATABASE_URL="$(owner_url "$database_name")" \
    MIGRATION_DATABASE_SECRET_REF="file:$owner_secret" \
    "$repo_root/.venv/bin/alembic" -c "$repo_root/backend/alembic.ini" "$@"
}

canonical_db="datariver_phase6b_canonical_verify"
create_database "$canonical_db"
alembic_for "$canonical_db" upgrade 0001
alembic_for "$canonical_db" stamp 0054
alembic_for "$canonical_db" upgrade 0055
alembic_for "$canonical_db" check

DATARIVER_SHARING_TEST_OWNER_DATABASE_URL="$(owner_url "$canonical_db")" \
DATARIVER_SHARING_TEST_OWNER_SECRET_REF="file:$owner_secret" \
DATARIVER_SHARING_TEST_APP_DATABASE_URL="$(app_url "$canonical_db")" \
DATARIVER_SHARING_TEST_APP_SECRET_REF="file:$app_secret" \
DATARIVER_SHARING_TEST_CONFIRM_ISOLATED=1 \
  "$repo_root/.venv/bin/pytest" \
  "$repo_root/backend/tests/integration/test_sharing_atomic_invocation_postgres.py" -q

if alembic_for "$canonical_db" downgrade 0054 >/dev/null 2>&1; then
  echo "Evidence-bearing 0055 downgrade unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$canonical_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0055" ]]

additive_db="datariver_phase6b_additive_verify"
create_database "$additive_db"
alembic_for "$additive_db" upgrade 0001
alembic_for "$additive_db" stamp 0055
alembic_for "$additive_db" downgrade 0054
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$additive_db" \
  >/dev/null <<'SQL'
BEGIN;
INSERT INTO platform.workspaces (id, slug, name, status, settings, version)
VALUES (
  '60000000-0000-4000-8000-000000000001',
  'phase6b-legacy-migration',
  'Phase 6B legacy migration',
  'ACTIVE',
  '{}'::jsonb,
  1
);
INSERT INTO iam.subjects (id, issuer, external_subject, display_name, active)
VALUES (
  '60000000-0000-4000-8000-000000000002',
  'phase6b-legacy-owner',
  'phase6b-legacy-owner',
  'Phase 6B legacy owner',
  true
);
INSERT INTO iam.workspace_memberships (
  workspace_id, subject_id, job_function, clearance, attributes, active,
  access_expires_at, version
) VALUES (
  '60000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000002',
  'DATA_OWNER',
  1,
  '{}'::jsonb,
  true,
  '2027-01-01 00:00:00+00',
  1
);
INSERT INTO knowledge.graphs (
  id, workspace_id, slug, name, graph_type, status, active_release_id,
  classification, version
) VALUES (
  '60000000-0000-4000-8000-000000000003',
  '60000000-0000-4000-8000-000000000001',
  'phase6b-legacy-graph',
  'Phase 6B legacy graph',
  'DOMAIN',
  'DRAFT',
  NULL,
  1,
  1
);
INSERT INTO knowledge.ontology_versions (
  id, workspace_id, graph_id, version, schema_document, checksum, status
) VALUES (
  '60000000-0000-4000-8000-000000000004',
  '60000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000003',
  '1.0.0',
  '{"entity_types":["Dataset"],"edge_types":[]}'::jsonb,
  repeat('a', 64),
  'ACTIVE'
);
INSERT INTO knowledge.releases (
  id, workspace_id, graph_id, release_no, ontology_version_id, content_hash,
  node_count, edge_count, manifest_ref, published_by, published_at
) VALUES (
  '60000000-0000-4000-8000-000000000005',
  '60000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000003',
  1,
  '60000000-0000-4000-8000-000000000004',
  repeat('b', 64),
  0,
  0,
  NULL,
  '60000000-0000-4000-8000-000000000002',
  '2026-01-01 00:00:00+00'
);
INSERT INTO sharing.api_products (
  id, workspace_id, slug, name, description, graph_id, classification,
  owner_id, state, current_version_id, version
) VALUES (
  '60000000-0000-4000-8000-000000000006',
  '60000000-0000-4000-8000-000000000001',
  'phase6b-legacy-product',
  'Phase 6B legacy product',
  'Migration preservation fixture',
  '60000000-0000-4000-8000-000000000003',
  1,
  '60000000-0000-4000-8000-000000000002',
  'PUBLISHED',
  NULL,
  2
);
INSERT INTO sharing.api_product_versions (
  id, workspace_id, product_id, graph_id, release_id, version_no, surface,
  contract_document, maximum_hops, maximum_nodes, timeout_ms, state,
  created_by, published_by, published_at
) VALUES (
  '60000000-0000-4000-8000-000000000007',
  '60000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000006',
  '60000000-0000-4000-8000-000000000003',
  '60000000-0000-4000-8000-000000000005',
  1,
  'NEIGHBORS',
  '{"scopes":["neighbors.query"],"query_template":"neighbors-v1"}'::jsonb,
  2,
  100,
  5000,
  'PUBLISHED',
  '60000000-0000-4000-8000-000000000002',
  '60000000-0000-4000-8000-000000000002',
  '2026-01-01 00:00:00+00'
);
UPDATE sharing.api_products
SET current_version_id = '60000000-0000-4000-8000-000000000007'
WHERE id = '60000000-0000-4000-8000-000000000006';
INSERT INTO sharing.consumer_grants (
  id, workspace_id, product_id, product_version_id, consumer_client_id, scopes,
  maximum_classification, requests_per_minute, monthly_quota, valid_from,
  expires_at, state, created_by, version
) VALUES (
  '60000000-0000-4000-8000-000000000008',
  '60000000-0000-4000-8000-000000000001',
  '60000000-0000-4000-8000-000000000006',
  '60000000-0000-4000-8000-000000000007',
  'phase6b-legacy-client',
  '["neighbors.query"]'::jsonb,
  1,
  100,
  1000,
  '2025-01-01 00:00:00+00',
  '2027-01-01 00:00:00+00',
  'ACTIVE',
  '60000000-0000-4000-8000-000000000002',
  1
);
INSERT INTO sharing.api_invocations (
  id, workspace_id, grant_id, invocation_key, requested_scope, request_id,
  occurred_at, units
) VALUES
  (
    '60000000-0000-4000-8000-000000000009',
    '60000000-0000-4000-8000-000000000001',
    '60000000-0000-4000-8000-000000000008',
    'phase6b-legacy-invocation-jan-a',
    'neighbors.query',
    'phase6b-legacy-request-jan-a',
    '2026-01-01 00:00:01+00',
    1
  ),
  (
    '60000000-0000-4000-8000-00000000000a',
    '60000000-0000-4000-8000-000000000001',
    '60000000-0000-4000-8000-000000000008',
    'phase6b-legacy-invocation-jan-b',
    'neighbors.query',
    'phase6b-legacy-request-jan-b',
    '2026-01-31 23:59:59+00',
    1
  ),
  (
    '60000000-0000-4000-8000-00000000000b',
    '60000000-0000-4000-8000-000000000001',
    '60000000-0000-4000-8000-000000000008',
    'phase6b-legacy-invocation-feb',
    'neighbors.query',
    'phase6b-legacy-request-feb',
    '2026-02-01 00:00:00+00',
    1
  );
COMMIT;
SQL
alembic_for "$additive_db" upgrade 0055
alembic_for "$additive_db" check
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$additive_db" \
  >/dev/null <<'SQL'
DO $$
BEGIN
  IF (
    SELECT count(*)
    FROM sharing.api_invocations
    WHERE id IN (
      '60000000-0000-4000-8000-000000000009',
      '60000000-0000-4000-8000-00000000000a',
      '60000000-0000-4000-8000-00000000000b'
    )
      AND evidence_kind = 'LEGACY_USAGE_V1'
      AND actor_id IS NULL
      AND result_hash IS NULL
  ) <> 3 THEN
    RAISE EXCEPTION 'Legacy invocation identity/evidence backfill was not preserved';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM sharing.consumer_grants
    WHERE id = '60000000-0000-4000-8000-000000000008'
      AND contract_version = 'LEGACY_CLIENT_V1'
      AND consumer_subject_id IS NULL
      AND consumer_issuer IS NULL
  ) THEN
    RAISE EXCEPTION 'Legacy grant identity/contract backfill was not preserved';
  END IF;
  IF (
    SELECT units
    FROM sharing.api_invocation_monthly_usage
    WHERE workspace_id = '60000000-0000-4000-8000-000000000001'
      AND grant_id = '60000000-0000-4000-8000-000000000008'
      AND month_start = '2026-01-01 00:00:00+00'
  ) IS DISTINCT FROM 2 OR (
    SELECT updated_at
    FROM sharing.api_invocation_monthly_usage
    WHERE workspace_id = '60000000-0000-4000-8000-000000000001'
      AND grant_id = '60000000-0000-4000-8000-000000000008'
      AND month_start = '2026-01-01 00:00:00+00'
  ) IS DISTINCT FROM '2026-01-31 23:59:59+00'::timestamptz THEN
    RAISE EXCEPTION 'January legacy monthly usage backfill is incorrect';
  END IF;
  IF (
    SELECT units
    FROM sharing.api_invocation_monthly_usage
    WHERE workspace_id = '60000000-0000-4000-8000-000000000001'
      AND grant_id = '60000000-0000-4000-8000-000000000008'
      AND month_start = '2026-02-01 00:00:00+00'
  ) IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'February legacy monthly usage backfill is incorrect';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM sharing.api_invocation_results
    WHERE workspace_id = '60000000-0000-4000-8000-000000000001'
  ) THEN
    RAISE EXCEPTION 'Legacy usage was assigned a fabricated replay body';
  END IF;
END
$$;
SQL

tamper_db="datariver_phase6b_tamper_verify"
create_database "$tamper_db"
alembic_for "$tamper_db" upgrade 0001
alembic_for "$tamper_db" stamp 0054
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "ALTER TABLE sharing.api_invocation_results DISABLE ROW LEVEL SECURITY" >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "Malformed-RLS canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "ALTER TABLE sharing.api_invocation_results ENABLE ROW LEVEL SECURITY" \
  -c "ALTER TABLE sharing.api_invocation_results FORCE ROW LEVEL SECURITY" \
  -c "ALTER TABLE sharing.api_invocations DISABLE TRIGGER api_invocation_exact_result" \
  >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "Disabled-trigger canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "ALTER TABLE sharing.api_invocations ENABLE TRIGGER api_invocation_exact_result" \
  -c "GRANT datariver_app TO datariver_relay" >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "Inherited SECDEF capability canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "REVOKE datariver_app FROM datariver_relay" \
  -c "GRANT datariver_app TO datariver_relay WITH INHERIT FALSE, SET TRUE" >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "SET-only app-role assumption canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "REVOKE datariver_app FROM datariver_relay" \
  -c "GRANT datariver_relay TO datariver_app WITH INHERIT FALSE, SET TRUE" >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "App SET-role capability canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "REVOKE datariver_relay FROM datariver_app" \
  -c "ALTER ROLE datariver_app SUPERUSER" >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "Unsafe app-role attributes canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "ALTER ROLE datariver_app NOSUPERUSER" \
  -c "ALTER TABLE sharing.api_invocations OWNER TO datariver_app" >/dev/null
if alembic_for "$tamper_db" upgrade 0055 >/dev/null 2>&1; then
  echo "Runtime-owned evidence table canonical bridge unexpectedly succeeded." >&2
  exit 1
fi
[[ "$(docker exec -i "$container_name" psql -XAt -U postgres -d "$tamper_db" \
  -c 'SELECT version_num FROM alembic_version')" == "0054" ]]
docker exec -i "$container_name" psql -v ON_ERROR_STOP=1 -U postgres -d "$tamper_db" \
  -c "ALTER TABLE sharing.api_invocations OWNER TO postgres" >/dev/null

first_hash="$("$repo_root/.venv/bin/python" "$repo_root/scripts/generate_initial_migration.py" \
  >/dev/null && shasum -a 256 "$repo_root/backend/alembic/versions/0001_initial_schema.py" \
  | awk '{print $1}')"
second_hash="$("$repo_root/.venv/bin/python" "$repo_root/scripts/generate_initial_migration.py" \
  >/dev/null && shasum -a 256 "$repo_root/backend/alembic/versions/0001_initial_schema.py" \
  | awk '{print $1}')"
[[ "$first_hash" == "$second_hash" ]]

printf 'atomic-sharing-postgres: PASS\ncanonical_sha256=%s\n' "$first_hash"
if [[ "$keep_container" == "1" ]]; then
  printf 'verification_container=%s\n' "$container_name"
fi
