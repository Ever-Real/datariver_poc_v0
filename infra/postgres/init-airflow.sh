#!/usr/bin/env sh
set -eu

export PGPASSWORD=$(cat /run/secrets/postgres_password)
airflow_password=$(cat /run/secrets/airflow_db_password)

psql --host postgres --username "${POSTGRES_USER:-datariver_owner}" \
  --dbname "${POSTGRES_DB:-datariver}" --set=ON_ERROR_STOP=1 \
  --set=airflow_password="$airflow_password" <<'SQL'
SELECT format('CREATE ROLE airflow LOGIN PASSWORD %L', :'airflow_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'airflow') \gexec
ALTER ROLE airflow WITH LOGIN PASSWORD :'airflow_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
SELECT 'CREATE DATABASE airflow OWNER airflow'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'airflow') \gexec
SQL
