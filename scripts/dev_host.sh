#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
runtime_dir="$root/runtime/source-host"

env_file_value() {
  local key=$1
  local fallback=$2
  local value=
  if [ -f "$root/.env" ]; then
    value=$(sed -n "s/^${key}=//p" "$root/.env" | tail -n 1)
  fi
  printf '%s' "${value:-$fallback}"
}

action=start
datahub_base_url="http://127.0.0.1:8080"
postgres_port=$(env_file_value POSTGRES_PORT 5432)
valkey_cache_port=$(env_file_value VALKEY_CACHE_PORT 6379)
valkey_queue_port=$(env_file_value VALKEY_QUEUE_PORT 6380)
keycloak_port=$(env_file_value KEYCLOAK_PORT 18081)
api_port=$(env_file_value API_PORT 38101)
web_port=$(env_file_value WEB_PORT 38102)
airflow_source_api_bridge_enabled=$(env_file_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED false)
airflow_source_api_bridge_port=$(env_file_value AIRFLOW_SOURCE_API_BRIDGE_PORT 38103)
enable_local_ollama=false
enable_neo4j=false
enable_airflow_source_bridge=$airflow_source_api_bridge_enabled

usage() {
  cat <<'EOF'
Usage: scripts/dev_host.sh [start|stop|status|migrate] [options]

Run the mutable DataRiver API, four workers and Vite from the checked-out source.
PostgreSQL, Valkey, SeaweedFS and (when selected) Keycloak remain Docker services.

The `migrate` action applies the Alembic migrations from this checkout using the
local PostgreSQL owner credential. Use it after pulling a source revision that
contains a database migration; it does not use the immutable migration image
from an offline bundle.

Options:
  --datahub-base-url URL   Approved DataHub GMS URL for host processes.
  --postgres-port PORT     Host PostgreSQL port (default: 5432).
  --valkey-cache-port PORT Host cache Valkey port (default: 6379).
  --valkey-queue-port PORT Host queue Valkey port (default: 6380).
  --keycloak-port PORT     Host Keycloak port (default: 18081).
  --api-port PORT          Host Uvicorn port (default: .env API_PORT or 38101).
  --web-port PORT          Host Vite port (default: .env WEB_PORT or 38102).
  --enable-airflow-source-bridge
                      Forward a private Docker bridge listener to the loopback
                      source API. Required only for Linux/WSL Airflow.
  --enable-local-ollama    Use native Ollama on 127.0.0.1:11434 for Mac development.
  --enable-neo4j           Use the local Neo4j projection on 127.0.0.1:17687.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    start|stop|status|migrate)
      action=$1
      ;;
    --datahub-base-url)
      shift
      datahub_base_url=${1:?--datahub-base-url requires a value}
      ;;
    --postgres-port)
      shift
      postgres_port=${1:?--postgres-port requires a value}
      ;;
    --valkey-cache-port)
      shift
      valkey_cache_port=${1:?--valkey-cache-port requires a value}
      ;;
    --valkey-queue-port)
      shift
      valkey_queue_port=${1:?--valkey-queue-port requires a value}
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
    --enable-local-ollama)
      enable_local_ollama=true
      ;;
    --enable-neo4j)
      enable_neo4j=true
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

is_running() {
  local file
  file=$(pid_file "$1")
  [ -s "$file" ] && kill -0 "$(cat "$file")" 2>/dev/null
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
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    local attempt=0
    while kill -0 "$pid" 2>/dev/null && [ "$attempt" -lt 20 ]; do
      sleep 0.5
      attempt=$((attempt + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$file"
}

show_status() {
  local name
  for name in api airflow-api-bridge outbox-relay upload-worker upload-validation-worker governance-apply-worker vite; do
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
    for process in vite governance-apply-worker upload-validation-worker upload-worker outbox-relay airflow-api-bridge api; do
      stop_process "$process"
    done
    echo "DataRiver source-host processes stopped."
    exit 0
    ;;
esac

python="$root/.venv/bin/python"
if [ ! -x "$python" ]; then
  echo "Missing $python. Run 'uv sync --frozen --all-extras' first." >&2
  exit 2
fi
if [ "$action" = start ] && ! command -v npm >/dev/null 2>&1; then
  echo "npm is required. Install the approved Node.js toolchain first." >&2
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
    postgres_governance_password valkey_cache_password valkey_queue_password
    datahub_token s3_access_key s3_secret_key
    keycloak_identity_admin_client_secret
  )
fi
for required in "${required_secrets[@]}"; do
  if [ ! -s "$root/secrets/$required" ]; then
    echo "Missing required secret file: $root/secrets/$required" >&2
    exit 2
  fi
done
if [ "$enable_neo4j" = true ] && [ ! -s "$root/secrets/neo4j_auth" ]; then
  echo "Missing required secret file: $root/secrets/neo4j_auth" >&2
  exit 2
fi
if [ "$enable_neo4j" = true ] && [ "$enable_local_ollama" != true ]; then
  echo "--enable-neo4j is the native Ollama development path; activate the intranet LLM and Neo4j System Settings, then start without either development adapter flag." >&2
  exit 2
fi

mkdir -p "$runtime_dir"
for process in api airflow-api-bridge outbox-relay upload-worker upload-validation-worker governance-apply-worker vite; do
  if is_running "$process"; then
    echo "DataRiver source-host process is already running: $process" >&2
    exit 2
  fi
done

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
export VALKEY_CACHE_URL="redis://127.0.0.1:$valkey_cache_port/0"
export VALKEY_QUEUE_URL="redis://127.0.0.1:$valkey_queue_port/0"
export VALKEY_CACHE_SECRET_REF="$(secret_ref valkey_cache_password)"
export VALKEY_QUEUE_SECRET_REF="$(secret_ref valkey_queue_password)"
export S3_ENDPOINT_URL="http://127.0.0.1:8333"
export S3_PUBLIC_ENDPOINT_URL="http://localhost:8333"
export S3_ACCESS_KEY_FILE="$root/secrets/s3_access_key"
export S3_SECRET_KEY_FILE="$root/secrets/s3_secret_key"
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
export SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=true
export SYSTEM_CONFIGURATION_RUNTIME_WORKSPACE_ID=00000000-0000-4000-8000-000000000100
export SYSTEM_CONFIGURATION_SECRET_ROOT="$root/secrets"
export VITE_API_BASE_URL=/api/v1
export VITE_API_PROXY_TARGET="http://127.0.0.1:$api_port"
export VITE_USE_POLLING=true
export VITE_OIDC_AUTHORITY="http://localhost:$keycloak_port/realms/datariver"
export VITE_OIDC_CLIENT_ID=datariver-web
export VITE_OIDC_REDIRECT_URI="$APP_PUBLIC_ORIGIN"
export VITE_OIDC_HIGH_ASSURANCE_ACR=2
export VITE_OIDC_PASSWORD_REAUTH_ACR=1
export LOCAL_OLLAMA_CHAT_ENABLED=false
export LOCAL_OLLAMA_EMBEDDING_ENABLED=false
export NEO4J_PROJECTION_ENABLED=false
export KNOWLEDGE_PIPELINE_ENABLED=false

if [ "$action" = migrate ]; then
  exec "$python" -m alembic -c "$root/backend/alembic.ini" upgrade head
fi

if [ "$enable_local_ollama" = true ]; then
  export LOCAL_OLLAMA_CHAT_ENABLED=true
  export LOCAL_OLLAMA_CHAT_BASE_URL=http://127.0.0.1:11434/v1
  export LOCAL_OLLAMA_CHAT_MODEL=datariver-gemma4-dev:0.1
  export LOCAL_OLLAMA_CHAT_TIMEOUT_SECONDS=60
  export LOCAL_OLLAMA_CHAT_CONTEXT_TOKENS=8192
  export LOCAL_OLLAMA_EMBEDDING_ENABLED=true
  export LOCAL_OLLAMA_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
  export LOCAL_OLLAMA_EMBEDDING_MODEL=bge-m3:latest
fi

if [ "$enable_neo4j" = true ]; then
  export NEO4J_PROJECTION_ENABLED=true
  export NEO4J_URI=bolt://127.0.0.1:17687
  export NEO4J_AUTH_SECRET_REF="$(secret_ref neo4j_auth)"
  export KNOWLEDGE_PIPELINE_ENABLED=true
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
    for process in vite governance-apply-worker upload-validation-worker upload-worker outbox-relay airflow-api-bridge api; do
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
  local configuration
  configuration=$(docker network inspect bridge --format '{{json .IPAM.Config}}' 2>/dev/null || true)
  "$python" "$root/scripts/source_api_bridge.py" \
    --print-docker-bridge-gateway "$configuration"
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
start_process vite "$root/frontend" npm run dev -- --host 127.0.0.1 --port "$web_port" --strictPort

sleep 2
for process in api airflow-api-bridge outbox-relay upload-worker upload-validation-worker governance-apply-worker vite; do
  if ! is_running "$process"; then
    echo "Source-host process failed during startup: $process. Read $runtime_dir/$process.err.log" >&2
    exit 1
  fi
done
cleanup_needed=false
trap - EXIT
show_status
