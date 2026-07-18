#!/usr/bin/env bash
set -euo pipefail

database_password=$(cat /run/secrets/airflow_db_password)
api_secret=$(cat /run/secrets/airflow_api_secret)
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://airflow:${database_password}@postgres:5432/airflow"
export AIRFLOW__API__SECRET_KEY="$api_secret"
# Airflow 3 task execution calls are JWT-authenticated.  Every component must
# derive the same adequately sized signing key without placing it in Compose.
export AIRFLOW__API_AUTH__JWT_SECRET="$(printf '%s' "$api_secret" | sha512sum | awk '{print $1}')"

password_file=/opt/airflow/auth/passwords.json
if [ ! -s "$password_file" ]; then
  umask 077
  printf '{"datariver-operator":"%s"}\n' \
    "$(cat /run/secrets/airflow_admin_password)" > "$password_file"
fi
chmod 0600 "$password_file"

exec /entrypoint "$@"
