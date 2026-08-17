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

# Read a key from the selected env file without inheriting shell environment.
# Usage: _env_value KEY [default]
_env_value() {
  local key="${1}" default="${2:-}"
  if [[ -f "${env_file}" ]]; then
    local raw
    raw="$(grep -E "^${key}=" "${env_file}" | tail -1 | cut -d= -f2- | sed "s/^['\"]//;s/['\"]$//")" || true
    printf '%s' "${raw:-${default}}"
  else
    printf '%s' "${default}"
  fi
}

# Docker Compose gives exported shell variables precedence over --env-file. Remove
# every key owned by the selected file from the Compose subprocess environment so
# that one ignored env file remains the authority without sourcing or printing it.
_compose_command() {
  local -a environment=(env)
  local line key
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]]; then
      key="${BASH_REMATCH[1]}"
      environment+=(-u "${key}")
    fi
  done < "${env_file}"
  compose=("${environment[@]}" docker compose --env-file "${env_file}" --file "${compose_file}")
}

case "${action}" in
  npm)
    command -v npm >/dev/null 2>&1 || fail "npm is required"
    cd -- "${repository_root}/frontend"
    [[ -d node_modules ]] || npm ci
    exec npm run poc
    ;;
  docker|start|build|stop|status|logs|web-restart)
    command -v docker >/dev/null 2>&1 || fail "docker is required"
    # Require the env file for all mutating Docker actions to prevent shell-env precedence
    # drift for keys defined in that file. status and logs accept a missing file.
    if [[ "${action}" == "status" || "${action}" == "logs" ]]; then
      if [[ -f "${env_file}" ]]; then
        _compose_command
      else
        compose=(docker compose --file "${compose_file}")
      fi
    else
      [[ -f "${env_file}" ]] || fail "env file not found: ${env_file} — copy deploy/poc/.env.example to deploy/poc/.env and configure it."
      _compose_command
    fi
    ;;
  reranker-restart)
    [[ -f "${env_file}" ]] || fail "env file not found: ${env_file} — copy deploy/poc/.env.example to deploy/poc/.env and configure it."
    command -v python3 >/dev/null 2>&1 || fail "python3 is required"
    ;;
  *)
    fail "usage: $0 [npm|docker|build|stop|status|logs|web-restart|reranker-restart]"
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
  web-restart)
    # Bounded application-only rebuild and recreate. Rebuilds and restarts only the
    # web container. Does NOT recreate Postgres, DataHub, Neo4j, Redis, or Airflow.
    "${compose[@]}" build web
    "${compose[@]}" up -d --no-deps --force-recreate web
    "${compose[@]}" ps web
    ;;
  reranker-restart)
    # Restart the local Mac llama.cpp reranker. Reads model and LLAMA_ARG_UBATCH
    # from the selected env file; does not inherit shell-side values for those keys.
    reranker_model="$(_env_value LOCAL_LLAMA_CPP_RERANKER_MODEL)"
    [[ -n "${reranker_model}" ]] || fail "LOCAL_LLAMA_CPP_RERANKER_MODEL is not set in ${env_file}"
    ubatch="$(_env_value LLAMA_ARG_UBATCH)"
    [[ -n "${ubatch}" ]] || fail "LLAMA_ARG_UBATCH is not set in ${env_file}"
    python3 "${script_dir}/local_reranker_service.py" stop
    LLAMA_ARG_UBATCH="${ubatch}" \
      python3 "${script_dir}/local_reranker_service.py" start --model "${reranker_model}"
    ;;
esac
