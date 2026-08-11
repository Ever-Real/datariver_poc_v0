#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "${script_dir}/.." && pwd -P)"
compose_file="${repository_root}/deploy/poc/docker-compose.poc.yaml"
env_file="${POC_ENV_FILE:-${repository_root}/deploy/poc/.env}"
action="${1:-docker}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

case "${action}" in
  npm)
    command -v npm >/dev/null 2>&1 || fail "npm is required"
    cd -- "${repository_root}/frontend"
    [[ -d node_modules ]] || npm ci
    exec npm run poc
    ;;
  docker|start|build|stop|status|logs)
    command -v docker >/dev/null 2>&1 || fail "docker is required"
    compose=(docker compose --file "${compose_file}")
    if [[ -f "${env_file}" ]]; then
      compose=(docker compose --env-file "${env_file}" --file "${compose_file}")
    fi
    ;;
  *)
    fail "usage: $0 [npm|docker|build|stop|status|logs]"
    ;;
esac

case "${action}" in
  docker|start)
    "${compose[@]}" up -d --build
    "${compose[@]}" ps
    ;;
  build)
    "${compose[@]}" build
    ;;
  stop)
    "${compose[@]}" down --remove-orphans
    ;;
  status)
    "${compose[@]}" ps
    ;;
  logs)
    "${compose[@]}" logs --follow web
    ;;
esac
