#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
runtime_dir="$root/runtime/source-host"
env_file_argument=${DATARIVER_ENV_FILE:-.env}

arguments=("$@")
for ((index = 0; index < ${#arguments[@]}; index++)); do
  if [ "${arguments[$index]}" = --env-file ]; then
    next_index=$((index + 1))
    [ "$next_index" -lt "${#arguments[@]}" ] || { echo "--env-file requires a path" >&2; exit 2; }
    env_file_argument=${arguments[$next_index]}
  fi
done
case "$env_file_argument" in
  /*) env_file=$env_file_argument ;;
  *) env_file="$root/$env_file_argument" ;;
esac

env_file_value() {
  local key=$1
  local fallback=$2
  local value=
  if [ -f "$env_file" ]; then
    value=$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)
  fi
  printf '%s' "${value:-$fallback}"
}

action=start
datahub_base_url=$(env_file_value DATAHUB_BASE_URL http://127.0.0.1:8080)
postgres_port=$(env_file_value POSTGRES_PORT 5432)
redis_cache_url=$(env_file_value REDIS_CACHE_URL redis://127.0.0.1:6379/0)
redis_delivery_url=$(env_file_value REDIS_DELIVERY_URL redis://127.0.0.1:6380/0)
s3_endpoint_url=$(env_file_value S3_ENDPOINT_URL http://127.0.0.1:9000)
s3_public_endpoint_url=$(env_file_value S3_PUBLIC_ENDPOINT_URL http://localhost:9000)
keycloak_port=$(env_file_value KEYCLOAK_PORT 18081)
api_port=$(env_file_value API_PORT 38101)
web_port=$(env_file_value WEB_PORT 38102)
airflow_source_api_bridge_enabled=$(env_file_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED false)
airflow_source_api_bridge_port=$(env_file_value AIRFLOW_SOURCE_API_BRIDGE_PORT 38103)
knowledge_source_worker_enabled=$(env_file_value KNOWLEDGE_SOURCE_WORKER_ENABLED false)
enable_airflow_source_bridge=$airflow_source_api_bridge_enabled

usage() {
  cat <<'EOF'
Usage: scripts/dev_host.sh [start|stop|status|migrate|preflight] [options]

Run the mutable DataRiver API, core workers, optional Knowledge source worker and Vite from
the checked-out source.
PostgreSQL and (when selected) Keycloak remain Docker services. Redis and
MinIO/S3 are external services configured through .env or the options below.

The `migrate` action applies the Alembic migrations from this checkout using the
local PostgreSQL owner credential. Use it after pulling a source revision that
contains a database migration; it does not use the immutable migration image
from an offline bundle.

Options:
  --env-file FILE          Ignored deployment environment file (default: DATARIVER_ENV_FILE or .env).
  --datahub-base-url URL   Approved DataHub GMS URL (default: .env DATAHUB_BASE_URL).
  --postgres-port PORT     Host PostgreSQL port (default: 5432).
  --redis-cache-url URL     External Redis cache URL (default: .env REDIS_CACHE_URL).
  --redis-delivery-url URL  External Redis delivery URL (default: .env REDIS_DELIVERY_URL).
  --s3-endpoint-url URL     External MinIO/S3 worker URL (default: .env S3_ENDPOINT_URL).
  --s3-public-endpoint-url URL
                           Browser-reachable MinIO/S3 URL used for signing.
  --keycloak-port PORT     Host Keycloak port (default: 18081).
  --api-port PORT          Host Uvicorn port (default: .env API_PORT or 38101).
  --web-port PORT          Host Vite port (default: .env WEB_PORT or 38102).
  --enable-airflow-source-bridge
                      Forward a private Docker bridge listener to the loopback
                      source API. Required only for Linux/WSL Airflow.
  Local model and Neo4j capabilities are read only from the selected environment file.
  preflight                Validate the final source-host Settings without starting processes.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    start|stop|status|migrate|preflight)
      action=$1
      ;;
    --env-file)
      shift
      env_file_argument=${1:?--env-file requires a path}
      ;;
    --datahub-base-url)
      shift
      datahub_base_url=${1:?--datahub-base-url requires a value}
      ;;
    --postgres-port)
      shift
      postgres_port=${1:?--postgres-port requires a value}
      ;;
    --redis-cache-url)
      shift
      redis_cache_url=${1:?--redis-cache-url requires a value}
      ;;
    --redis-delivery-url)
      shift
      redis_delivery_url=${1:?--redis-delivery-url requires a value}
      ;;
    --s3-endpoint-url)
      shift
      s3_endpoint_url=${1:?--s3-endpoint-url requires a value}
      ;;
    --s3-public-endpoint-url)
      shift
      s3_public_endpoint_url=${1:?--s3-public-endpoint-url requires a value}
      ;;
    --keycloak-port)
      shift
      keycloak_port=${1:?--keycloak-port requires a value}
      ;;
    --api-port)
      shift
      api_port=${1:?--api-port requires a value}
      ;;
    --web-port)
      shift
      web_port=${1:?--web-port requires a value}
      ;;
    --enable-airflow-source-bridge)
      enable_airflow_source_bridge=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

pid_file() {
  printf '%s/%s.pid\n' "$runtime_dir" "$1"
}

process_is_active() {
  local pid=$1
  kill -0 "$pid" 2>/dev/null || return 1
  local state
  state=$(ps -p "$pid" -o stat= 2>/dev/null | tr -d '[:space:]' || true)
  [[ "$state" != Z* ]]
}

is_running() {
  local file
  file=$(pid_file "$1")
  [ -s "$file" ] && process_is_active "$(cat "$file")"
}

stop_process() {
  local name=$1
  local file
  file=$(pid_file "$name")
  if [ ! -s "$file" ]; then
    return
  fi
  local pid
  pid=$(cat "$file")
  if process_is_active "$pid"; then
    kill -TERM "$pid" 2>/dev/null || true
    local attempt=0
    while process_is_active "$pid" && [ "$attempt" -lt 20 ]; do
      sleep 0.5
      attempt=$((attempt + 1))
    done
    if process_is_active "$pid"; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$file"
}

stop_owned_vite_processes() {
  local current_uid
  current_uid=$(id -u)
  if ! command -v pgrep >/dev/null 2>&1; then
    return
  fi
  local pid process_uid command_line
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    [ "$pid" != "$$" ] || continue
    process_uid=$(ps -p "$pid" -o uid= 2>/dev/null | tr -d '[:space:]')
    [ "$process_uid" = "$current_uid" ] || continue
    command_line=$(ps -ww -p "$pid" -o command= 2>/dev/null || true)
    if [[ "$command_line" != *"$root/frontend/node_modules/vite/bin/vite.js"* ]] &&
      [[ "$command_line" != *"$root/frontend/node_modules/.bin/vite"* ]]; then
      continue
    fi
    if [[ "$command_line" != *"--port $web_port"* ]] &&
      [[ "$command_line" != *"--port=$web_port"* ]]; then
      continue
    fi
    kill -TERM "$pid" 2>/dev/null || true
    local attempt=0
    while process_is_active "$pid" && [ "$attempt" -lt 20 ]; do
      sleep 0.5
      attempt=$((attempt + 1))
    done
    if process_is_active "$pid"; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
    printf 'Stopped orphaned DataRiver Vite process (pid %s).\n' "$pid"
  done < <(pgrep -f '[v]ite' || true)
}

show_status() {
  local name
  for name in api airflow-api-bridge outbox-relay upload-worker upload-validation-worker governance-apply-worker knowledge-source-worker vite; do
    if is_running "$name"; then
      printf '%-25s running (pid %s)\n' "$name" "$(cat "$(pid_file "$name")")"
    else
      printf '%-25s stopped\n' "$name"
    fi
  done
}

case "$action" in
  status)
    show_status
    exit 0
    ;;
  stop)
    for process in vite knowledge-source-worker governance-apply-worker upload-validation-worker upload-worker outbox-relay airflow-api-bridge api; do
      stop_process "$process"
    done
    stop_owned_vite_processes
    echo "DataRiver source-host processes stopped."
    exit 0
    ;;
esac

python="$root/.venv/bin/python"
if [ ! -x "$python" ]; then
  echo "Missing $python. Run 'uv sync --frozen --all-extras' first." >&2
  exit 2
fi
node=$(command -v node || true)
vite_entry="$root/frontend/node_modules/vite/bin/vite.js"
if [ "$action" = start ] && { [ -z "$node" ] || [ ! -f "$vite_entry" ]; }; then
  echo "Node.js and installed Vite dependencies are required. Run 'npm ci' in frontend first." >&2
  exit 2
fi
if [ "$action" = start ] && [ "$enable_airflow_source_bridge" = true ] && [ "$(uname -s)" != Linux ]; then
  echo "--enable-airflow-source-bridge is supported only on Linux/WSL source hosts." >&2
  exit 2
fi
if [ "$action" = start ] && [ "$enable_airflow_source_bridge" = true ] && ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to discover the private Airflow source-host bridge address." >&2
  exit 2
fi

required_secrets=(postgres_password)
if [ "$action" = start ]; then
  required_secrets+=(
    postgres_app_password postgres_relay_password postgres_upload_password
    postgres_governance_password
    redis_cache_password redis_delivery_password
    datahub_token s3_access_key s3_secret_key
    keycloak_identity_admin_client_secret
  )
  if [ "$knowledge_source_worker_enabled" = true ]; then
    required_secrets+=(
      postgres_knowledge_password s3_knowledge_access_key s3_knowledge_secret_key
    )
  fi
fi
for required in "${required_secrets[@]}"; do
  if [ ! -s "$root/secrets/$required" ]; then
    echo "Missing required secret file: $root/secrets/$required" >&2
    exit 2
  fi
done

load_env_file() {
  local line key value
  [ -f "$env_file" ] || { echo "Missing deployment environment file: $env_file" >&2; exit 2; }
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key=${line%%=*}
    value=${line#*=}
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
      echo "Invalid environment key in $env_file: $key" >&2
      exit 2
    }
    if [[ "$value" == \"*\" ]] && [ "${#value}" -ge 2 ]; then
      value=${value:1:${#value}-2}
    fi
    export "$key=$value"
  done < "$env_file"
}

load_env_file
export LOCAL_INFERENCE_SOURCE_HOST_ENABLED=true
if [ "${NEO4J_PROJECTION_ENABLED:-false}" = true ] && [ ! -s "$root/secrets/neo4j_auth" ]; then
  echo "Missing required secret file: $root/secrets/neo4j_auth" >&2
  exit 2
fi
mkdir -p "$runtime_dir"
if [ "$action" = start ]; then
  for process in api airflow-api-bridge outbox-relay upload-worker upload-validation-worker governance-apply-worker knowledge-source-worker vite; do
    if is_running "$process"; then
      echo "DataRiver source-host process is already running: $process" >&2
      exit 2
    fi
  done
fi

require_available_port() {
  local label=$1
  local port=$2
  if ! "$python" -c '
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", int(sys.argv[1])))
' "$port" 2>/dev/null; then
    echo "$label port 127.0.0.1:$port is already in use." >&2
    echo "Inspect it with: sudo ss -ltnp \"sport = :$port\"" >&2
    exit 2
  fi
}

if [ "$action" = start ]; then
  stop_owned_vite_processes
  require_available_port API "$api_port"
  require_available_port Vite "$web_port"
fi

secret_ref() {
  printf 'file:%s/secrets/%s' "$root" "$1"
}

export APP_PUBLIC_ORIGIN="http://localhost:$web_port"
export APP_CORS_ORIGINS="$APP_PUBLIC_ORIGIN"
export APP_TRUSTED_HOSTS="localhost,127.0.0.1,host.docker.internal,apisix"
export DATABASE_URL="postgresql+asyncpg://datariver_app@127.0.0.1:$postgres_port/datariver"
export DATABASE_SECRET_REF="$(secret_ref postgres_app_password)"
export MIGRATION_DATABASE_URL="postgresql+asyncpg://datariver_owner@127.0.0.1:$postgres_port/datariver"
export MIGRATION_DATABASE_SECRET_REF="$(secret_ref postgres_password)"
export RELAY_DATABASE_URL="postgresql+asyncpg://datariver_relay@127.0.0.1:$postgres_port/datariver"
export RELAY_DATABASE_SECRET_REF="$(secret_ref postgres_relay_password)"
export UPLOAD_DATABASE_URL="postgresql+asyncpg://datariver_upload@127.0.0.1:$postgres_port/datariver"
export UPLOAD_DATABASE_SECRET_REF="$(secret_ref postgres_upload_password)"
export GOVERNANCE_DATABASE_URL="postgresql+asyncpg://datariver_governance@127.0.0.1:$postgres_port/datariver"
export GOVERNANCE_DATABASE_SECRET_REF="$(secret_ref postgres_governance_password)"
export KNOWLEDGE_DATABASE_URL="postgresql+asyncpg://datariver_knowledge@127.0.0.1:$postgres_port/datariver"
export KNOWLEDGE_DATABASE_SECRET_REF="$(secret_ref postgres_knowledge_password)"
export REDIS_CACHE_URL="$redis_cache_url"
export REDIS_DELIVERY_URL="$redis_delivery_url"
export REDIS_CACHE_SECRET_REF="$(secret_ref redis_cache_password)"
export REDIS_DELIVERY_SECRET_REF="$(secret_ref redis_delivery_password)"
export S3_ENDPOINT_URL="$s3_endpoint_url"
export S3_PUBLIC_ENDPOINT_URL="$s3_public_endpoint_url"
export S3_ACCESS_KEY_FILE="$root/secrets/s3_access_key"
export S3_SECRET_KEY_FILE="$root/secrets/s3_secret_key"
export S3_KNOWLEDGE_ACCESS_KEY_FILE="$root/secrets/s3_knowledge_access_key"
export S3_KNOWLEDGE_SECRET_KEY_FILE="$root/secrets/s3_knowledge_secret_key"
export KNOWLEDGE_SOURCE_SPOOL_DIRECTORY="$runtime_dir/knowledge-spool"
export OIDC_ISSUER="http://localhost:$keycloak_port/realms/datariver"
export OIDC_JWKS_URL="http://localhost:$keycloak_port/realms/datariver/protocol/openid-connect/certs"
export IDENTITY_ADMIN_ENABLED=true
export IDENTITY_ADMIN_BASE_URL="http://127.0.0.1:$keycloak_port"
export IDENTITY_ADMIN_REALM=datariver
export IDENTITY_ADMIN_CLIENT_ID=datariver-identity-admin
export IDENTITY_ADMIN_CLIENT_SECRET_REF="$(secret_ref keycloak_identity_admin_client_secret)"
export IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED=true
export DATAHUB_BASE_URL="$datahub_base_url"
export DATAHUB_SECRET_REF="$(secret_ref datahub_token)"
export SEED_PROFILE=none
export WATCHFILES_FORCE_POLLING=true
export SYSTEM_CONFIGURATION_SECRET_ROOT="$root/secrets"
export VITE_API_BASE_URL=/api/v1
export VITE_API_PROXY_TARGET="http://127.0.0.1:$api_port"
export VITE_USE_POLLING=true
export VITE_OIDC_AUTHORITY="http://localhost:$keycloak_port/realms/datariver"
export VITE_OIDC_CLIENT_ID=datariver-web
export VITE_OIDC_REDIRECT_URI="$APP_PUBLIC_ORIGIN"
export VITE_OIDC_HIGH_ASSURANCE_ACR=2
export VITE_OIDC_PASSWORD_REAUTH_ACR=1
if [ "$action" = migrate ]; then
  exec "$python" -m alembic -c "$root/backend/alembic.ini" upgrade head
fi

if [ "$action" = preflight ]; then
  PYTHONPATH="$root/backend/src" exec "$python" -c '
import json

from datariver.config import Settings

settings = Settings(_env_file=None)
source_analysis = (
    settings.local_ollama_chat_enabled and settings.local_ollama_embedding_enabled
) or (
    settings.intranet_openai_compatible_chat_enabled
    and settings.intranet_openai_compatible_embedding_enabled
)
print(
    json.dumps(
        {
            "knowledge_source_analysis": "CONFIGURED" if source_analysis else "NOT_CONFIGURED",
            "local_inference_source_host": settings.local_inference_source_host_enabled,
            "neo4j_projection": (
                "CONFIGURED" if settings.neo4j_projection_enabled else "NOT_CONFIGURED"
            ),
            "runtime_activation": settings.system_configuration_runtime_activation_enabled,
        },
        sort_keys=True,
    )
)
'
fi

start_process() {
  local name=$1
  local workdir=$2
  shift 2
  (
    cd "$workdir"
    exec "$@"
  ) >"$runtime_dir/$name.out.log" 2>"$runtime_dir/$name.err.log" &
  printf '%s\n' "$!" >"$(pid_file "$name")"
}

cleanup_needed=true
cleanup_on_error() {
  local status=$?
  if [ "$cleanup_needed" = true ] && [ "$status" -ne 0 ]; then
    for process in vite knowledge-source-worker governance-apply-worker upload-validation-worker upload-worker outbox-relay airflow-api-bridge api; do
      stop_process "$process"
    done
  fi
}
trap cleanup_on_error EXIT

start_process api "$root" "$python" -m uvicorn datariver.main:app \
  --host 127.0.0.1 --port "$api_port" --reload --reload-dir backend/src --no-access-log

api_ready=false
for _attempt in $(seq 1 60); do
  if ! is_running api; then
    echo "Source API exited before readiness. Read $runtime_dir/api.err.log" >&2
    exit 1
  fi
  if curl --fail --silent --show-error "http://127.0.0.1:$api_port/api/v1/health/ready" >/dev/null 2>&1; then
    api_ready=true
    break
  fi
  sleep 0.5
done
if [ "$api_ready" != true ]; then
  stop_process api
  echo "Source API did not become ready. Run migration and inspect $runtime_dir/api.err.log" >&2
  exit 1
fi

docker_bridge_gateway() {
  local inspection
  if ! inspection=$(docker network inspect bridge); then
    echo "Docker could not inspect its default bridge network." >&2
    return 1
  fi
  "$python" "$root/scripts/source_api_bridge.py" \
    --print-docker-bridge-gateway "$inspection"
}

if [ "$enable_airflow_source_bridge" = true ]; then
  bridge_gateway=$(docker_bridge_gateway) || {
    stop_process api
    echo "Could not determine a private Docker bridge gateway for Airflow source-host access." >&2
    echo "Verify 'docker network inspect bridge' and keep the source API loopback-only." >&2
    exit 2
  }
  start_process airflow-api-bridge "$root" "$python" "$root/scripts/source_api_bridge.py" \
    --listen-host "$bridge_gateway" \
    --listen-port "$airflow_source_api_bridge_port" \
    --target-port "$api_port"
  sleep 0.5
  if ! is_running airflow-api-bridge; then
    stop_process api
    echo "Airflow source API bridge failed. Read $runtime_dir/airflow-api-bridge.err.log" >&2
    exit 1
  fi
fi

start_process outbox-relay "$root" "$python" -m datariver.workers.outbox_relay
start_process upload-worker "$root" "$python" -m datariver.workers.upload_worker
start_process upload-validation-worker "$root" "$python" -m datariver.workers.upload_validation
start_process governance-apply-worker "$root" "$python" -m datariver.workers.governance_apply
if [ "${KNOWLEDGE_SOURCE_WORKER_ENABLED:-false}" = true ]; then
  mkdir -p "$KNOWLEDGE_SOURCE_SPOOL_DIRECTORY"
  start_process knowledge-source-worker "$root" "$python" -m datariver.workers.knowledge_source
fi
start_process vite "$root/frontend" "$node" "$vite_entry" \
  --host 127.0.0.1 --port "$web_port" --strictPort

sleep 2
for process in api airflow-api-bridge outbox-relay upload-worker upload-validation-worker governance-apply-worker vite; do
  if ! is_running "$process"; then
    echo "Source-host process failed during startup: $process. Read $runtime_dir/$process.err.log" >&2
    exit 1
  fi
done
if [ "${KNOWLEDGE_SOURCE_WORKER_ENABLED:-false}" = true ] &&
   ! is_running knowledge-source-worker; then
  echo "Source-host process failed during startup: knowledge-source-worker. Read $runtime_dir/knowledge-source-worker.err.log" >&2
  exit 1
fi
cleanup_needed=false
trap - EXIT
show_status
