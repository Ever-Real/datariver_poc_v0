#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file_argument=${DATARIVER_ENV_FILE:-.env}

if [ "${1:-}" = --env-file ]; then
  shift
  env_file_argument=${1:?--env-file requires a path}
  shift
fi

case "$env_file_argument" in
  /*) env_file=$env_file_argument ;;
  *) env_file="$root/$env_file_argument" ;;
esac
[ -f "$env_file" ] || { echo "Missing deployment environment file: $env_file" >&2; exit 2; }

export DATARIVER_ENV_FILE="$env_file"
connector_network=datariver-connectors
if grep -q '^DATARIVER_CONNECTOR_NETWORK=' "$env_file"; then
  connector_network=$(
    sed -n 's/^DATARIVER_CONNECTOR_NETWORK=//p' "$env_file" | tail -n 1
  )
fi
case "$connector_network" in
  ''|-*|.|..|*[!A-Za-z0-9_.-]*)
    echo "DATARIVER_CONNECTOR_NETWORK contains unsupported characters." >&2
    exit 2
    ;;
esac
for argument in "$@"; do
  case "$argument" in
    up|run|create|start)
      DATARIVER_CONNECTOR_NETWORK=$connector_network \
        "$root/scripts/ensure_connector_network.sh"
      break
      ;;
  esac
done
exec docker compose --env-file "$env_file" "$@"
