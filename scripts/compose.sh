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
exec docker compose --env-file "$env_file" "$@"
