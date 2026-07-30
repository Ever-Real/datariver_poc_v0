#!/usr/bin/env sh
set -eu

app_password=$(cat /run/secrets/postgres_app_password)
relay_password=$(cat /run/secrets/postgres_relay_password)
upload_password=$(cat /run/secrets/postgres_upload_password)
governance_password=$(cat /run/secrets/postgres_governance_password)
knowledge_password=$(cat /run/secrets/postgres_knowledge_password)
quality_password=$(cat /run/secrets/postgres_quality_password)
catalog_profile_password=$(cat /run/secrets/postgres_catalog_profile_password)
export_password=$(cat /run/secrets/postgres_export_password)
retention_scheduler_password=$(cat /run/secrets/postgres_retention_scheduler_password)
archive_password=$(cat /run/secrets/postgres_archive_password)
bootstrap_password=$(cat /run/secrets/postgres_bootstrap_password)
keycloak_password=$(cat /run/secrets/keycloak_db_password)

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$app_password" \
  --set=relay_password="$relay_password" \
  --set=upload_password="$upload_password" \
  --set=governance_password="$governance_password" \
  --set=knowledge_password="$knowledge_password" \
  --set=quality_password="$quality_password" \
  --set=catalog_profile_password="$catalog_profile_password" \
  --set=export_password="$export_password" \
  --set=retention_scheduler_password="$retention_scheduler_password" \
  --set=archive_password="$archive_password" \
  --set=bootstrap_password="$bootstrap_password" \
  --set=keycloak_password="$keycloak_password" <<'SQL'
SELECT format('CREATE ROLE datariver_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') \gexec
SELECT format('CREATE ROLE datariver_relay LOGIN PASSWORD %L', :'relay_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') \gexec
SELECT format('CREATE ROLE datariver_upload LOGIN PASSWORD %L', :'upload_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') \gexec
SELECT format('CREATE ROLE datariver_governance LOGIN PASSWORD %L', :'governance_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') \gexec
SELECT format('CREATE ROLE datariver_knowledge LOGIN PASSWORD %L', :'knowledge_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_knowledge') \gexec
SELECT format('CREATE ROLE datariver_quality LOGIN PASSWORD %L', :'quality_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_quality') \gexec
SELECT format(
  'CREATE ROLE datariver_catalog_profile LOGIN PASSWORD %L '
  'NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
  :'catalog_profile_password'
)
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = 'datariver_catalog_profile'
) \gexec
SELECT format('CREATE ROLE datariver_export LOGIN PASSWORD %L', :'export_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_export') \gexec
SELECT format('CREATE ROLE datariver_retention_scheduler LOGIN PASSWORD %L', :'retention_scheduler_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_retention_scheduler') \gexec
SELECT format('CREATE ROLE datariver_archive LOGIN PASSWORD %L', :'archive_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_archive') \gexec
SELECT format('CREATE ROLE datariver_bootstrap LOGIN PASSWORD %L', :'bootstrap_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') \gexec
SELECT format('CREATE ROLE keycloak LOGIN PASSWORD %L', :'keycloak_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') \gexec

ALTER ROLE datariver_app WITH LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE datariver_relay WITH LOGIN PASSWORD :'relay_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
ALTER ROLE datariver_upload WITH LOGIN PASSWORD :'upload_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
ALTER ROLE datariver_governance WITH LOGIN PASSWORD :'governance_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
ALTER ROLE datariver_knowledge WITH LOGIN PASSWORD :'knowledge_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
DO $datariver$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS candidate
    WHERE candidate.rolname <> 'datariver_knowledge'
      AND pg_has_role('datariver_knowledge', candidate.oid, 'MEMBER')
  ) THEN
    RAISE EXCEPTION
      'datariver_knowledge must not inherit or SET ROLE to another principal';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS candidate
    WHERE candidate.rolname <> 'datariver_knowledge'
      AND NOT candidate.rolsuper
      AND pg_has_role(candidate.oid, 'datariver_knowledge', 'MEMBER')
  ) THEN
    RAISE EXCEPTION
      'datariver_knowledge must not be assumable by another non-superuser principal';
  END IF;
END
$datariver$;
ALTER ROLE datariver_quality WITH LOGIN PASSWORD :'quality_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
DO $datariver$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS candidate
    WHERE candidate.rolname <> 'datariver_quality'
      AND pg_has_role('datariver_quality', candidate.oid, 'MEMBER')
  ) THEN
    RAISE EXCEPTION
      'datariver_quality must not inherit or SET ROLE to another principal';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS candidate
    WHERE candidate.rolname <> 'datariver_quality'
      AND NOT candidate.rolsuper
      AND pg_has_role(candidate.oid, 'datariver_quality', 'MEMBER')
  ) THEN
    RAISE EXCEPTION
      'datariver_quality must not be assumable by another non-superuser principal';
  END IF;
END
$datariver$;
ALTER ROLE datariver_catalog_profile WITH LOGIN PASSWORD :'catalog_profile_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
DO $datariver$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS candidate
    WHERE candidate.rolname <> 'datariver_catalog_profile'
      AND pg_has_role('datariver_catalog_profile', candidate.oid, 'MEMBER')
  ) THEN
    RAISE EXCEPTION
      'datariver_catalog_profile must not inherit or SET ROLE to another principal';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS candidate
    WHERE candidate.rolname <> 'datariver_catalog_profile'
      AND NOT candidate.rolsuper
      AND pg_has_role(candidate.oid, 'datariver_catalog_profile', 'MEMBER')
  ) THEN
    RAISE EXCEPTION
      'datariver_catalog_profile must not be assumable by another non-superuser principal';
  END IF;
END
$datariver$;
ALTER ROLE datariver_export WITH LOGIN PASSWORD :'export_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE datariver_retention_scheduler WITH LOGIN PASSWORD :'retention_scheduler_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE datariver_archive WITH LOGIN PASSWORD :'archive_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE datariver_bootstrap WITH LOGIN PASSWORD :'bootstrap_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
ALTER ROLE keycloak WITH LOGIN PASSWORD :'keycloak_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- The init hook also serves as an idempotent existing-volume reconciliation command. Resolve
-- grants only when the Phase 2 schema is already present; on a new volume Alembic grants them
-- after migration, while on an upgraded old volume this repairs roles created after 0042 ran.
SELECT 'GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention TO datariver_retention_scheduler'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT SELECT ON platform.workspaces, iam.subjects, iam.workspace_memberships, iam.access_roles, iam.access_role_assignments, authz.policy_decisions, retention.policy_versions, retention.policy_class_rules, retention.legal_holds, retention.erasure_requests, retention.erasure_request_events, assistant.chat_sessions TO datariver_retention_scheduler'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT SELECT, INSERT ON retention.execution_jobs, retention.execution_events TO datariver_retention_scheduler'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec

SELECT 'GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention TO datariver_archive'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT SELECT ON platform.workspaces, iam.subjects, iam.workspace_memberships, iam.access_roles, iam.access_role_assignments, authz.policy_decisions, retention.policy_versions, retention.policy_class_rules, retention.legal_holds, retention.erasure_requests, retention.erasure_request_events, assistant.chat_sessions, retention.execution_jobs, retention.execution_attempts, retention.archive_capability_attestations, retention.immutable_archive_receipts TO datariver_archive'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT INSERT ON retention.archive_capability_attestations, retention.immutable_archive_receipts, retention.execution_attempts TO datariver_archive'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT SELECT, INSERT ON retention.execution_events TO datariver_archive'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT UPDATE (state, next_attempt_at, attempt_count, lease_epoch, lease_token_hash, lease_owner_fingerprint, lease_until, archive_receipt_id, archive_manifest_hash, last_failure_code, version, updated_at) ON retention.execution_jobs TO datariver_archive'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec
SELECT 'GRANT UPDATE (state, stage, evidence_hash, external_response_hash, failure_code, finished_at) ON retention.execution_attempts TO datariver_archive'
WHERE to_regclass('retention.execution_jobs') IS NOT NULL \gexec

-- Reconcile the profile collector to one fixed projection-function capability. The schema USAGE
-- privilege only permits name resolution; all direct catalog/quality object access stays revoked.
SELECT 'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog, quality FROM datariver_catalog_profile'
WHERE to_regnamespace('catalog') IS NOT NULL
  AND to_regnamespace('quality') IS NOT NULL \gexec
SELECT 'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog, quality FROM datariver_catalog_profile'
WHERE to_regnamespace('catalog') IS NOT NULL
  AND to_regnamespace('quality') IS NOT NULL \gexec
SELECT 'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA catalog, quality FROM datariver_catalog_profile'
WHERE to_regnamespace('catalog') IS NOT NULL
  AND to_regnamespace('quality') IS NOT NULL \gexec
SELECT 'REVOKE ALL PRIVILEGES ON SCHEMA catalog, quality FROM datariver_catalog_profile'
WHERE to_regnamespace('catalog') IS NOT NULL
  AND to_regnamespace('quality') IS NOT NULL \gexec
SELECT 'GRANT USAGE ON SCHEMA catalog TO datariver_catalog_profile'
WHERE to_regnamespace('catalog') IS NOT NULL \gexec
DO $datariver$
DECLARE
  profile_function record;
  overloaded_profile_function text;
BEGIN
  SELECT procedure.proname
  INTO overloaded_profile_function
  FROM pg_proc AS procedure
  JOIN pg_namespace AS namespace
    ON namespace.oid = procedure.pronamespace
  WHERE namespace.nspname = 'catalog'
    AND procedure.proname IN (
      'read_profile_target_v1',
      'project_asset_profile_v1'
    )
  GROUP BY procedure.proname
  HAVING count(*) > 1
  LIMIT 1;

  IF overloaded_profile_function IS NOT NULL THEN
    RAISE EXCEPTION
      'catalog.% must have exactly one canonical signature',
      overloaded_profile_function;
  END IF;

  FOR profile_function IN
    SELECT procedure.oid::regprocedure AS function_identity
    FROM pg_proc AS procedure
    JOIN pg_namespace AS namespace
      ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'catalog'
      AND procedure.proname IN (
        'read_profile_target_v1',
        'project_asset_profile_v1'
      )
  LOOP
    EXECUTE format(
      'GRANT EXECUTE ON FUNCTION %s TO datariver_catalog_profile',
      profile_function.function_identity
    );
  END LOOP;
END
$datariver$;

SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak') \gexec
SQL
