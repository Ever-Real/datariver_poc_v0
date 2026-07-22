#!/usr/bin/env sh
set -eu

app_password=$(cat /run/secrets/postgres_app_password)
relay_password=$(cat /run/secrets/postgres_relay_password)
upload_password=$(cat /run/secrets/postgres_upload_password)
governance_password=$(cat /run/secrets/postgres_governance_password)
export_password=$(cat /run/secrets/postgres_export_password)
bootstrap_password=$(cat /run/secrets/postgres_bootstrap_password)
keycloak_password=$(cat /run/secrets/keycloak_db_password)

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$app_password" \
  --set=relay_password="$relay_password" \
  --set=upload_password="$upload_password" \
  --set=governance_password="$governance_password" \
  --set=export_password="$export_password" \
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
SELECT format('CREATE ROLE datariver_export LOGIN PASSWORD %L', :'export_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_export') \gexec
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
ALTER ROLE datariver_export WITH LOGIN PASSWORD :'export_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE datariver_bootstrap WITH LOGIN PASSWORD :'bootstrap_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
ALTER ROLE keycloak WITH LOGIN PASSWORD :'keycloak_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak') \gexec
SQL
