#!/usr/bin/env bash
set -euo pipefail

database_password=$(cat /run/secrets/airflow_db_password)
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://airflow:${database_password}@postgres:5432/airflow"
export AIRFLOW__API__SECRET_KEY="$(cat /run/secrets/airflow_api_secret)"

password_file=/opt/airflow/auth/passwords.json
if [ ! -s "$password_file" ]; then
  umask 077
  printf '{"datariver-operator":"%s"}\n' \
    "$(cat /run/secrets/airflow_admin_password)" > "$password_file"
fi
chmod 0600 "$password_file"

exec /entrypoint "$@"
