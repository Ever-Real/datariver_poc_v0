#!/usr/bin/env sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file_argument=${DATARIVER_ENV_FILE:-.env}
case "$env_file_argument" in
  /*) env_file=$env_file_argument ;;
  *) env_file="$root/$env_file_argument" ;;
esac

[ -f "$env_file" ] || {
  echo "DataRiver environment file not found: $env_file" >&2
  exit 2
}

docker compose --env-file "$env_file" -f "$root/compose.yaml" \
  exec -T postgres sh -ec \
  'export PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)"; exec sh /docker-entrypoint-initdb.d/010_roles.sh'

echo "PostgreSQL runtime roles reconciled with the mounted secret files."
