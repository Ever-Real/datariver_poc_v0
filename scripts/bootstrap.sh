#!/usr/bin/env sh
set -eu

datahub_token_file=
datahub_base_url=
host_development=false
mac_development=false
wsl_preparation=false
source_host_airflow_bridge=false
enable_knowledge_source_worker=false
env_file_argument=.env
while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file)
      shift
      [ "$#" -gt 0 ] || { echo "--env-file requires a path" >&2; exit 2; }
      env_file_argument=$1
      ;;
    --host-development)
      host_development=true
      ;;
    --mac-development)
      mac_development=true
      ;;
    --wsl-preparation)
      wsl_preparation=true
      ;;
    --source-host-airflow-bridge)
      source_host_airflow_bridge=true
      ;;
    --enable-knowledge-source-worker)
      enable_knowledge_source_worker=true
      ;;
    --datahub-base-url)
      shift
      [ "$#" -gt 0 ] || { echo "--datahub-base-url requires a value" >&2; exit 2; }
      datahub_base_url=$1
      ;;
    --datahub-token-file)
      shift
      [ "$#" -gt 0 ] || { echo "--datahub-token-file requires a path" >&2; exit 2; }
      datahub_token_file=$1
      ;;
    *)
      echo "unexpected argument; use a documented named option" >&2
      exit 2
      ;;
  esac
  shift
done

selected_profiles=0
[ "$host_development" = true ] && selected_profiles=$((selected_profiles + 1))
[ "$mac_development" = true ] && selected_profiles=$((selected_profiles + 1))
[ "$wsl_preparation" = true ] && selected_profiles=$((selected_profiles + 1))
if [ "$selected_profiles" -gt 1 ]; then
  echo "--host-development, --mac-development and --wsl-preparation are mutually exclusive" >&2
  exit 2
fi
if [ "$source_host_airflow_bridge" = true ] && [ "$host_development" != true ]; then
  echo "--source-host-airflow-bridge requires --host-development" >&2
  exit 2
fi
if [ "$source_host_airflow_bridge" = true ] && [ "$(uname -s)" != Linux ]; then
  echo "--source-host-airflow-bridge is supported only on Linux/WSL source hosts" >&2
  exit 2
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$env_file_argument" in
  /*) env_file=$env_file_argument ;;
  *) env_file="$root/$env_file_argument" ;;
esac

secrets_dir="$root/secrets"
runtime_dir="$root/runtime"
keycloak_runtime_dir="$runtime_dir/keycloak"
retention_control_file="$runtime_dir/retention-execution.enabled"
datahub_token_path="$secrets_dir/datahub_token"
for protected_path in \
  "$env_file" \
  "$secrets_dir" \
  "$runtime_dir" \
  "$keycloak_runtime_dir" \
  "$keycloak_runtime_dir/datariver-realm.json" \
  "$retention_control_file"; do
  if [ -L "$protected_path" ]; then
    echo "Bootstrap refuses symbolic links for managed paths." >&2
    exit 2
  fi
done
if [ -d "$secrets_dir" ]; then
  for existing_secret in \
    "$secrets_dir"/* \
    "$secrets_dir"/.[!.]* \
    "$secrets_dir"/..?*; do
    if [ -L "$existing_secret" ]; then
      echo "Bootstrap refuses symbolic links in the secrets directory." >&2
      exit 2
    fi
  done
fi
if [ -n "$datahub_token_file" ]; then
  [ ! -L "$datahub_token_file" ] &&
    [ -f "$datahub_token_file" ] && [ -s "$datahub_token_file" ] &&
    [ -r "$datahub_token_file" ] || {
    echo "DataHub token file must be an existing, readable, non-empty regular file: $datahub_token_file" >&2
    exit 2
  }
  if [ -e "$datahub_token_path" ] && [ "$datahub_token_file" -ef "$datahub_token_path" ]; then
    datahub_token_file=
  fi
elif [ -s "$datahub_token_path" ] && [ -r "$datahub_token_path" ]; then
  :
elif [ "$mac_development" != true ]; then
  echo "DataHub token file is required. Install it at secrets/datahub_token or use --datahub-token-file with an approved file path." >&2
  exit 2
fi

[ -f "$env_file" ] || cp "$root/.env.example" "$env_file"

env_value() {
  env_name=$1
  sed -n "s/^${env_name}=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

env_is_true() {
  env_name=$1
  env_current_value=$(env_value "$env_name" | tr '[:upper:]' '[:lower:]')
  [ "$env_current_value" = true ]
}

env_is_nonempty() {
  env_name=$1
  [ -n "$(env_value "$env_name")" ]
}

local_knowledge_inference_is_ready() {
  if [ "$mac_development" = true ]; then
    env_is_true LOCAL_OLLAMA_EMBEDDING_ENABLED &&
      env_is_nonempty LOCAL_OLLAMA_EMBEDDING_BASE_URL &&
      env_is_nonempty LOCAL_OLLAMA_EMBEDDING_MODEL &&
      ! env_is_true INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED &&
      ! env_is_true INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED
    return
  fi
  env_is_true LOCAL_OLLAMA_CHAT_ENABLED &&
    env_is_true LOCAL_OLLAMA_EMBEDDING_ENABLED &&
    env_is_nonempty LOCAL_OLLAMA_CHAT_BASE_URL &&
    env_is_nonempty LOCAL_OLLAMA_CHAT_MODEL &&
    env_is_nonempty LOCAL_OLLAMA_EMBEDDING_BASE_URL &&
    env_is_nonempty LOCAL_OLLAMA_EMBEDDING_MODEL
}

intranet_knowledge_inference_is_ready() {
  env_is_true INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED &&
    env_is_true INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_CHAT_BASE_URL &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_CHAT_MODEL &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_CHAT_API_KEY_SECRET_REF &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_EMBEDDING_BASE_URL &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_EMBEDDING_MODEL &&
    env_is_nonempty INTRANET_OPENAI_COMPATIBLE_EMBEDDING_API_KEY_SECRET_REF
}

knowledge_inference_is_ready() {
  if [ "$wsl_preparation" = true ]; then
    intranet_knowledge_inference_is_ready
    return
  fi
  local_knowledge_inference_is_ready ||
    intranet_knowledge_inference_is_ready
}

if [ "$enable_knowledge_source_worker" = true ] &&
  ! knowledge_inference_is_ready; then
  echo "--enable-knowledge-source-worker requires one complete Chat+Embedding pair in $env_file (local Ollama or intranet OpenAI-compatible)." >&2
  exit 2
fi

umask 077
mkdir -p "$secrets_dir"
mkdir -p "$keycloak_runtime_dir"
if [ ! -f "$retention_control_file" ]; then
  printf '%s\n' DISABLED > "$retention_control_file"
fi
for existing_file in "$secrets_dir"/* "$keycloak_runtime_dir"/datariver-realm.json; do
  if [ -f "$existing_file" ]; then
    chmod 0600 "$existing_file"
  fi
done

if [ -n "$datahub_token_file" ]; then
  datahub_token_temp=$(mktemp "$secrets_dir/.datahub_token.tmp.XXXXXX")
  trap 'rm -f "$datahub_token_temp"' 0 1 2 15
  cp "$datahub_token_file" "$datahub_token_temp"
  [ -s "$datahub_token_temp" ] || {
    echo "DataHub token staging produced an empty file." >&2
    exit 2
  }
  chmod 0600 "$datahub_token_temp"
  mv -f "$datahub_token_temp" "$datahub_token_path"
  datahub_token_temp=
  trap - 0 1 2 15
fi

random_secret() {
  openssl rand -base64 "$1" | tr -d '\n'
}

ensure_random_secret() {
  name=$1
  bytes=$2
  path="$secrets_dir/$name"
  if [ ! -s "$path" ]; then
    random_secret "$bytes" > "$path"
  fi
}

ensure_random_secret postgres_password 32
ensure_random_secret postgres_app_password 32
ensure_random_secret postgres_relay_password 32
ensure_random_secret postgres_upload_password 32
ensure_random_secret postgres_governance_password 32
ensure_random_secret postgres_knowledge_password 32
ensure_random_secret postgres_export_password 32
ensure_random_secret postgres_retention_scheduler_password 32
ensure_random_secret postgres_archive_password 32
ensure_random_secret postgres_bootstrap_password 32
ensure_random_secret keycloak_db_password 32
ensure_random_secret airflow_db_password 32
ensure_random_secret airflow_api_secret 48
ensure_random_secret airflow_client_secret 32
ensure_random_secret keycloak_identity_admin_client_secret 32
ensure_random_secret airflow_admin_password 24
ensure_random_secret keycloak_demo_password 18
ensure_random_secret keycloak_admin_password 24
ensure_random_secret grafana_admin_password 24
if [ ! -s "$secrets_dir/redis_cache_password" ] && [ -s "$secrets_dir/valkey_cache_password" ]; then
  cp "$secrets_dir/valkey_cache_password" "$secrets_dir/redis_cache_password"
fi
if [ ! -s "$secrets_dir/redis_delivery_password" ] && [ -s "$secrets_dir/valkey_queue_password" ]; then
  cp "$secrets_dir/valkey_queue_password" "$secrets_dir/redis_delivery_password"
fi
ensure_random_secret redis_cache_password 32
ensure_random_secret redis_delivery_password 32
# These files are inert unless a development administrator explicitly activates
# an intranet OpenAI-compatible LLM profile. Operators replace them through the
# approved secret channel; bootstrap never enables the provider on their behalf.
ensure_random_secret intranet_llm_chat_api_key 32
ensure_random_secret intranet_llm_embedding_api_key 32
ensure_random_secret intranet_llm_reranker_api_key 32
if ! grep -Eq '^neo4j/[0-9a-f]{64}$' "$secrets_dir/neo4j_auth" 2>/dev/null; then
  # Neo4j parses NEO4J_AUTH as username/password, so use a delimiter-safe
  # hexadecimal password rather than generic base64 output.
  printf 'neo4j/%s' "$(openssl rand -hex 32)" > "$secrets_dir/neo4j_auth"
fi
if [ ! -s "$datahub_token_path" ]; then
  if [ "$mac_development" = true ]; then
    # The bundled local DataHub v1.6.0 topology has authentication disabled,
    # but the application still requires a non-empty provider credential file.
    # Keep the development-only placeholder out of Git and do not reuse it.
    random_secret 32 > "$secrets_dir/datahub_token"
  else
    echo "DataHub token file preflight invariant failed." >&2
    exit 2
  fi
fi
if [ ! -s "$secrets_dir/s3_access_key" ]; then
  random_secret 18 | tr '/+' 'AB' | tr -d '=' > "$secrets_dir/s3_access_key"
fi
ensure_random_secret s3_secret_key 36
if [ ! -s "$secrets_dir/s3_export_access_key" ]; then
  random_secret 18 | tr '/+' 'AB' | tr -d '=' > "$secrets_dir/s3_export_access_key"
fi
ensure_random_secret s3_export_secret_key 36
if [ ! -s "$secrets_dir/s3_knowledge_access_key" ]; then
  random_secret 18 | tr '/+' 'AB' | tr -d '=' > "$secrets_dir/s3_knowledge_access_key"
fi
ensure_random_secret s3_knowledge_secret_key 36
if [ ! -s "$secrets_dir/s3_archive_access_key" ]; then
  random_secret 18 | tr '/+' 'AB' | tr -d '=' > "$secrets_dir/s3_archive_access_key"
fi
ensure_random_secret s3_archive_secret_key 36
demo_password=$(cat "$secrets_dir/keycloak_demo_password")
airflow_client_secret=$(cat "$secrets_dir/airflow_client_secret")
identity_admin_client_secret=$(cat "$secrets_dir/keycloak_identity_admin_client_secret")
escaped_demo_password=$(printf '%s' "$demo_password" | sed 's/[\/&]/\\&/g')
escaped_airflow_client_secret=$(printf '%s' "$airflow_client_secret" | sed 's/[\/&]/\\&/g')
escaped_identity_admin_client_secret=$(printf '%s' "$identity_admin_client_secret" | sed 's/[\/&]/\\&/g')
web_public_origin=http://localhost:8080
if [ "$host_development" = true ]; then
  web_public_origin=http://localhost:38102
elif [ "$mac_development" = true ]; then
  web_public_origin=http://localhost:38102
fi
escaped_web_public_origin=$(printf '%s' "$web_public_origin" | sed 's/[\/&]/\\&/g')
sed -e "s/__DEMO_PASSWORD__/$escaped_demo_password/g" \
  -e "s/__AIRFLOW_CLIENT_SECRET__/$escaped_airflow_client_secret/g" \
  -e "s/__IDENTITY_ADMIN_CLIENT_SECRET__/$escaped_identity_admin_client_secret/g" \
  -e "s/__WEB_PUBLIC_ORIGIN__/$escaped_web_public_origin/g" \
  "$root/infra/keycloak/datariver-realm.template.json" \
  > "$keycloak_runtime_dir/datariver-realm.json"

set_env_value() {
  name=$1
  value=$2
  temp_file="$env_file.tmp.$$"
  if grep -q "^${name}=" "$env_file"; then
    sed "s|^${name}=.*|${name}=${value}|" "$env_file" > "$temp_file"
  else
    cp "$env_file" "$temp_file"
    printf '%s=%s\n' "$name" "$value" >> "$temp_file"
  fi
  mv "$temp_file" "$env_file"
}

set_env_value DATARIVER_ENV_FILE "$env_file_argument"
set_env_value DATARIVER_CONNECTOR_NETWORK datariver-connectors

if [ "$host_development" = true ]; then
  set_env_value APP_PUBLIC_ORIGIN "$web_public_origin"
  set_env_value APP_CORS_ORIGINS "$web_public_origin"
  set_env_value API_PORT 38101
  set_env_value WEB_PORT 38102
  set_env_value POSTGRES_PORT 5432
  set_env_value VALKEY_CACHE_PORT 6379
  set_env_value VALKEY_QUEUE_PORT 6380
  set_env_value KEYCLOAK_PORT 18081
  set_env_value APISIX_PORT 9080
  # Airflow remains containerized while API/workers run from the source host.
  # A WSL/Linux checkout may still run its mutable source API on Windows.
  # Enable the bridge only when the API itself runs in this Linux host.
  if [ "$source_host_airflow_bridge" = true ]; then
    set_env_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED true
    set_env_value AIRFLOW_SOURCE_API_BRIDGE_PORT 38103
    set_env_value DATARIVER_API_BASE_URL http://host.docker.internal:38103
  else
    set_env_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED false
    set_env_value DATARIVER_API_BASE_URL http://host.docker.internal:38101
  fi
  set_env_value OIDC_ISSUER http://localhost:18081/realms/datariver
  set_env_value OIDC_PUBLIC_AUTHORITY http://localhost:18081/realms/datariver
  set_env_value OIDC_PUBLIC_ORIGIN http://localhost:18081
  set_env_value IDENTITY_ADMIN_ENABLED true
  set_env_value IDENTITY_ADMIN_BASE_URL http://keycloak:8080
  set_env_value IDENTITY_ADMIN_CLIENT_SECRET_REF file:/run/secrets/keycloak_identity_admin_client_secret
  set_env_value IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED true
fi
if [ "$mac_development" = true ]; then
  # Keep this Mac development topology disjoint from common local DataHub,
  # frontend and API bindings.  DataHub remains the external provider on the
  # host, while containers reach it through Docker Desktop's host gateway.
  set_env_value APP_PUBLIC_ORIGIN "$web_public_origin"
  set_env_value APP_CORS_ORIGINS "$web_public_origin"
  set_env_value WEB_PORT 38102
  set_env_value API_PORT 38101
  set_env_value POSTGRES_PORT 15432
  set_env_value KEYCLOAK_PORT 18081
  set_env_value APISIX_PORT 19080
  # Docker Desktop resolves this gateway to the native source API without
  # giving Airflow a DataHub token.
  set_env_value DATARIVER_API_BASE_URL http://host.docker.internal:38101
  set_env_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED false
  set_env_value OIDC_ISSUER http://localhost:18081/realms/datariver
  set_env_value OIDC_PUBLIC_AUTHORITY http://localhost:18081/realms/datariver
  set_env_value OIDC_PUBLIC_ORIGIN http://localhost:18081
  set_env_value IDENTITY_ADMIN_ENABLED true
  set_env_value IDENTITY_ADMIN_BASE_URL http://keycloak:8080
  set_env_value IDENTITY_ADMIN_CLIENT_SECRET_REF file:/run/secrets/keycloak_identity_admin_client_secret
  set_env_value IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED true
  set_env_value DATAHUB_BASE_URL http://host.docker.internal:8080
  # MinIO Community supports exact cluster-wide CORS, not PutBucketCors.
  set_env_value S3_CORS_MANAGEMENT_MODE external
  set_env_value UI_DATAHUB_URL http://localhost:19002
  set_env_value LOCAL_OLLAMA_CHAT_ENABLED true
  set_env_value LOCAL_OLLAMA_CHAT_BASE_URL http://host.docker.internal:11434/v1
  set_env_value LOCAL_OLLAMA_CHAT_MODEL datariver-gemma4-dev:0.1
  set_env_value LOCAL_OLLAMA_CHAT_TIMEOUT_SECONDS 60
  set_env_value LOCAL_OLLAMA_CHAT_CONTEXT_TOKENS 8192
  set_env_value SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED false
  set_env_value CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED true
  set_env_value UI_GRAPH_URL http://localhost:17474
fi
if [ "$wsl_preparation" = true ]; then
  # This is a containerized, non-HA preparation profile. External DataHub,
  # MinIO, Airflow, telemetry and LLM endpoints remain operator inputs.
  set_env_value APP_ENV development
  set_env_value APP_PUBLIC_ORIGIN http://localhost:8080
  set_env_value APP_CORS_ORIGINS http://localhost:8080
  set_env_value WEB_PORT 8080
  set_env_value API_PORT 8000
  set_env_value POSTGRES_PORT 5432
  set_env_value KEYCLOAK_PORT 8081
  # Tokens carry the browser-reachable issuer.  API-side key retrieval remains
  # on the private Compose network through OIDC_JWKS_URL below.
  set_env_value OIDC_ISSUER http://localhost:8081/realms/datariver
  set_env_value OIDC_JWKS_URL http://keycloak:8080/realms/datariver/protocol/openid-connect/certs
  set_env_value OIDC_PUBLIC_AUTHORITY http://localhost:8081/realms/datariver
  set_env_value OIDC_PUBLIC_ORIGIN http://localhost:8081
  set_env_value REDIS_CACHE_URL redis://redis-cache:6379/0
  set_env_value REDIS_DELIVERY_URL redis://redis-delivery:6379/0
  set_env_value DATABASE_POOL_SIZE 4
  set_env_value DATABASE_POOL_MAX_OVERFLOW 0
  set_env_value WORKER_DATABASE_POOL_SIZE 1
  set_env_value WORKER_DATABASE_POOL_MAX_OVERFLOW 0
  set_env_value DATAHUB_MAX_CONCURRENCY 8
  set_env_value NEO4J_MAXIMUM_CONNECTION_POOL_SIZE 4
  set_env_value SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED false
  set_env_value LOCAL_OLLAMA_CHAT_ENABLED false
  set_env_value LOCAL_OLLAMA_EMBEDDING_ENABLED false
  set_env_value NEO4J_PROJECTION_ENABLED false
  set_env_value KNOWLEDGE_PIPELINE_ENABLED false
fi
if [ -n "$datahub_base_url" ]; then
  set_env_value DATAHUB_BASE_URL "$datahub_base_url"
fi
if [ "$enable_knowledge_source_worker" = true ]; then
  set_env_value KNOWLEDGE_DATABASE_URL postgresql+asyncpg://datariver_knowledge@postgres:5432/datariver
  set_env_value KNOWLEDGE_DATABASE_SECRET_REF file:/run/secrets/postgres_knowledge_password
  set_env_value S3_KNOWLEDGE_ACCESS_KEY_FILE /run/secrets/s3_knowledge_access_key
  set_env_value S3_KNOWLEDGE_SECRET_KEY_FILE /run/secrets/s3_knowledge_secret_key
  set_env_value KNOWLEDGE_SOURCE_WORKER_ENABLED true
fi

# File-based Compose secrets are bind mounts, so container users with different
# UIDs need read permission. Host access remains restricted by the 0700 parents.
chmod 0700 "$secrets_dir" "$keycloak_runtime_dir"
chmod 0444 "$secrets_dir"/* "$keycloak_runtime_dir/datariver-realm.json"
chmod 0644 "$retention_control_file"

echo "Bootstrap files created in $env_file. Keep the environment and secrets directory private and out of Git."
