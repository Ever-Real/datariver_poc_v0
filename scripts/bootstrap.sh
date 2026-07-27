#!/usr/bin/env sh
set -eu

datahub_token_file=
datahub_base_url=
host_development=false
portable_development=false
mac_development=false
wsl_preparation=false
source_host_airflow_bridge=false
intranet_source_host=false
web_public_origin_argument=
oidc_public_origin_argument=
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
    --portable-development)
      portable_development=true
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
    --intranet-source-host)
      intranet_source_host=true
      ;;
    --web-public-origin)
      shift
      [ "$#" -gt 0 ] || { echo "--web-public-origin requires an HTTPS origin" >&2; exit 2; }
      web_public_origin_argument=$1
      ;;
    --oidc-public-origin)
      shift
      [ "$#" -gt 0 ] || { echo "--oidc-public-origin requires an HTTPS origin" >&2; exit 2; }
      oidc_public_origin_argument=$1
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
[ "$portable_development" = true ] && selected_profiles=$((selected_profiles + 1))
[ "$mac_development" = true ] && selected_profiles=$((selected_profiles + 1))
[ "$wsl_preparation" = true ] && selected_profiles=$((selected_profiles + 1))
if [ "$selected_profiles" -gt 1 ]; then
  echo "--host-development, --portable-development, --mac-development and --wsl-preparation are mutually exclusive" >&2
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
if [ "$intranet_source_host" = true ]; then
  if [ "$host_development" != true ]; then
    echo "--intranet-source-host requires --host-development" >&2
    exit 2
  fi
  if [ "$(uname -s)" != Linux ]; then
    echo "--intranet-source-host is supported only on Linux/WSL source hosts" >&2
    exit 2
  fi
  if [ -z "$web_public_origin_argument" ] || [ -z "$oidc_public_origin_argument" ]; then
    echo "--intranet-source-host requires both --web-public-origin and --oidc-public-origin" >&2
    exit 2
  fi
elif [ -n "$web_public_origin_argument" ] || [ -n "$oidc_public_origin_argument" ]; then
  echo "Public intranet origins require --intranet-source-host" >&2
  exit 2
fi

validate_intranet_origin() {
  origin_name=$1
  origin_value=$2
  case "$origin_value" in
    https://*) ;;
    *)
      echo "$origin_name must be an HTTPS origin" >&2
      exit 2
      ;;
  esac
  origin_authority=${origin_value#https://}
  case "$origin_authority" in
    ""|*[!A-Za-z0-9.-]*|.*|*.)
      echo "$origin_name must contain only one DNS name or IPv4 address without a path or port" >&2
      exit 2
      ;;
  esac
}

if [ "$intranet_source_host" = true ]; then
  validate_intranet_origin "--web-public-origin" "$web_public_origin_argument"
  validate_intranet_origin "--oidc-public-origin" "$oidc_public_origin_argument"
  if [ "$web_public_origin_argument" = "$oidc_public_origin_argument" ]; then
    echo "The Web and OIDC public origins must use distinct hostnames" >&2
    exit 2
  fi
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$env_file_argument" in
  /*) env_file=$env_file_argument ;;
  *) env_file="$root/$env_file_argument" ;;
esac

secrets_dir="$root/secrets"
runtime_dir="$root/runtime"
keycloak_runtime_dir="$runtime_dir/keycloak"
identity_runtime_dir="$runtime_dir/identity"
demo_identity_state="$identity_runtime_dir/local-demo-identities.json"
legacy_demo_identity_state="$keycloak_runtime_dir/local-demo-identities.json"
retention_control_file="$runtime_dir/retention-execution.enabled"
datahub_token_path="$secrets_dir/datahub_token"
for protected_path in \
  "$env_file" \
  "$secrets_dir" \
  "$runtime_dir" \
  "$keycloak_runtime_dir" \
  "$identity_runtime_dir" \
  "$keycloak_runtime_dir/datariver-realm.json" \
  "$demo_identity_state" \
  "$legacy_demo_identity_state" \
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

umask 077

set_env_value() {
  name=$1
  value=$2
  temp_file="$env_file.tmp.$$"
  DATARIVER_BOOTSTRAP_ENV_NAME="$name" \
    DATARIVER_BOOTSTRAP_ENV_VALUE="$value" \
    awk '
      BEGIN {
        target = ENVIRON["DATARIVER_BOOTSTRAP_ENV_NAME"]
        replacement = target "=" ENVIRON["DATARIVER_BOOTSTRAP_ENV_VALUE"]
        emitted = 0
      }
      index($0, target "=") == 1 {
        if (!emitted) {
          print replacement
          emitted = 1
        }
        next
      }
      { print }
      END {
        if (!emitted) {
          print replacement
        }
      }
    ' "$env_file" > "$temp_file"
  mv "$temp_file" "$env_file"
}

ensure_required_env_value_from_example() {
  name=$1
  current_value=$(sed -n "s/^${name}=//p" "$env_file" | tail -n 1 | tr -d '\r')
  [ -z "$current_value" ] || return 0
  value=$(sed -n "s/^${name}=//p" "$root/.env.example" | tail -n 1 | tr -d '\r')
  if [ -z "$value" ]; then
    echo "Required environment template value is unavailable: $name" >&2
    exit 2
  fi
  set_env_value "$name" "$value"
  printf 'Added required environment setting from .env.example: %s\n' "$name"
}

backfill_required_env_values() {
  [ -f "$env_file" ] || return 0
  for required_env_name in \
    OIDC_AUDIENCE \
    DATAHUB_EXPECTED_VERSION \
    S3_BUCKET_QUARANTINE \
    S3_BUCKET_ACCEPTED; do
    ensure_required_env_value_from_example "$required_env_name"
  done
}

# Existing ignored deployment files are repaired before secret preflight so a
# missing external token cannot prevent non-secret configuration migration.
backfill_required_env_values

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
backfill_required_env_values

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

mkdir -p "$secrets_dir"
mkdir -p "$keycloak_runtime_dir"
mkdir -p "$identity_runtime_dir"
if [ -e "$legacy_demo_identity_state" ]; then
  [ -f "$legacy_demo_identity_state" ] || {
    echo "Legacy local demo identity state must be a regular file." >&2
    exit 2
  }
  if [ -e "$demo_identity_state" ]; then
    cmp -s "$legacy_demo_identity_state" "$demo_identity_state" || {
      echo "Conflicting local demo identity state files require manual review." >&2
      exit 2
    }
    migrated_state_dir=$(mktemp -d "$identity_runtime_dir/migrated-keycloak-import.XXXXXX")
    mv "$legacy_demo_identity_state" "$migrated_state_dir/local-demo-identities.json"
  else
    mv "$legacy_demo_identity_state" "$demo_identity_state"
  fi
fi
if [ ! -f "$retention_control_file" ]; then
  printf '%s\n' DISABLED > "$retention_control_file"
fi
for existing_file in \
  "$secrets_dir"/* \
  "$keycloak_runtime_dir"/datariver-realm.json \
  "$demo_identity_state"; do
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
oidc_public_origin=http://localhost:8081
if [ "$host_development" = true ]; then
  web_public_origin=http://localhost:38102
  oidc_public_origin=http://localhost:18081
elif [ "$mac_development" = true ]; then
  web_public_origin=http://localhost:38102
fi
if [ "$intranet_source_host" = true ]; then
  web_public_origin=$web_public_origin_argument
  oidc_public_origin=$oidc_public_origin_argument
fi
escaped_web_public_origin=$(printf '%s' "$web_public_origin" | sed 's/[\/&]/\\&/g')
sed -e "s/__DEMO_PASSWORD__/$escaped_demo_password/g" \
  -e "s/__AIRFLOW_CLIENT_SECRET__/$escaped_airflow_client_secret/g" \
  -e "s/__IDENTITY_ADMIN_CLIENT_SECRET__/$escaped_identity_admin_client_secret/g" \
  -e "s/__WEB_PUBLIC_ORIGIN__/$escaped_web_public_origin/g" \
  "$root/infra/keycloak/datariver-realm.template.json" \
  > "$keycloak_runtime_dir/datariver-realm.json"

set_env_value DATARIVER_ENV_FILE "$env_file_argument"
set_env_value DATARIVER_CONNECTOR_NETWORK datariver-connectors
# Legacy profiles may still carry the retired database-overlay activation
# switch. Normalize it before any source/container Settings validation.
set_env_value SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED false

if [ "$host_development" = true ]; then
  set_env_value APP_ENV development
  set_env_value APP_PUBLIC_ORIGIN "$web_public_origin"
  set_env_value APP_CORS_ORIGINS "$web_public_origin"
  set_env_value API_PORT 38101
  set_env_value WEB_PORT 38102
  set_env_value POSTGRES_PORT 5432
  set_env_value VALKEY_CACHE_PORT 6379
  set_env_value VALKEY_QUEUE_PORT 6380
  set_env_value KEYCLOAK_PORT 18081
  set_env_value APISIX_PORT 9080
  set_env_value REDIS_CACHE_URL redis://127.0.0.1:6379/0
  set_env_value REDIS_DELIVERY_URL redis://127.0.0.1:6380/0
  source_host_neo4j_uri=$(env_value NEO4J_URI)
  source_host_neo4j_bolt_port=$(env_value NEO4J_BOLT_PORT)
  [ -n "$source_host_neo4j_bolt_port" ] || source_host_neo4j_bolt_port=17687
  case "$source_host_neo4j_uri" in
    ""|\
    bolt://neo4j:7687|bolt://neo4j:7687/|\
    neo4j://neo4j:7687|neo4j://neo4j:7687/|\
    bolt://neo4j:"$source_host_neo4j_bolt_port"|\
    bolt://neo4j:"$source_host_neo4j_bolt_port"/|\
    neo4j://neo4j:"$source_host_neo4j_bolt_port"|\
    neo4j://neo4j:"$source_host_neo4j_bolt_port"/)
      set_env_value NEO4J_URI "bolt://127.0.0.1:$source_host_neo4j_bolt_port"
      set_env_value NEO4J_ALLOWED_HOSTS 127.0.0.1
      ;;
    bolt://127.0.0.1:*)
      set_env_value NEO4J_ALLOWED_HOSTS 127.0.0.1
      ;;
  esac
  set_env_value NEO4J_SOURCE_HOST_ENABLED true
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
  set_env_value OIDC_ISSUER "$oidc_public_origin/realms/datariver"
  set_env_value OIDC_PUBLIC_AUTHORITY "$oidc_public_origin/realms/datariver"
  set_env_value OIDC_PUBLIC_ORIGIN "$oidc_public_origin"
  set_env_value IDENTITY_ADMIN_ENABLED true
  set_env_value IDENTITY_ADMIN_BASE_URL http://keycloak:8080
  set_env_value IDENTITY_ADMIN_CLIENT_SECRET_REF file:/run/secrets/keycloak_identity_admin_client_secret
  set_env_value IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED true
  set_env_value OIDC_HARDWARE_WEBAUTHN_ENABLED false
  set_env_value WORKSPACE_SELECTION_ENABLED false
  set_env_value INTRANET_SOURCE_HOST_ENABLED "$intranet_source_host"
fi
if [ "$portable_development" = true ]; then
  # Portable development runs the reviewed source on either linux/arm64 or
  # linux/amd64. Provider endpoints and model identities remain operator-owned
  # values in the selected environment file.
  set_env_value APP_ENV development
  set_env_value APP_PUBLIC_ORIGIN http://localhost:8080
  set_env_value APP_CORS_ORIGINS http://localhost:8080
  set_env_value WEB_PORT 8080
  set_env_value API_PORT 8000
  set_env_value POSTGRES_PORT 5432
  set_env_value KEYCLOAK_PORT 8081
  set_env_value APISIX_PORT 9080
  set_env_value DATARIVER_API_BASE_URL http://api:8000
  set_env_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED false
  set_env_value OIDC_ISSUER http://localhost:8081/realms/datariver
  set_env_value OIDC_JWKS_URL http://keycloak:8080/realms/datariver/protocol/openid-connect/certs
  set_env_value OIDC_PUBLIC_AUTHORITY http://localhost:8081/realms/datariver
  set_env_value OIDC_PUBLIC_ORIGIN http://localhost:8081
  set_env_value IDENTITY_ADMIN_ENABLED true
  set_env_value IDENTITY_ADMIN_BASE_URL http://keycloak:8080
  set_env_value IDENTITY_ADMIN_CLIENT_SECRET_REF file:/run/secrets/keycloak_identity_admin_client_secret
  set_env_value IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED true
  set_env_value OIDC_HARDWARE_WEBAUTHN_ENABLED false
  set_env_value WORKSPACE_SELECTION_ENABLED false
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
  set_env_value OIDC_HARDWARE_WEBAUTHN_ENABLED false
  set_env_value WORKSPACE_SELECTION_ENABLED false
  set_env_value DATAHUB_BASE_URL http://host.docker.internal:8080
  # MinIO Community supports exact cluster-wide CORS, not PutBucketCors.
  set_env_value S3_CORS_MANAGEMENT_MODE external
  set_env_value UI_DATAHUB_URL http://localhost:19002
  # Model endpoints, identities and enablement stay operator-owned in the
  # ignored environment file. This profile never selects or creates a model.
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
  # Airflow is external for the preparation source-host profile. The private
  # Docker-to-host bridge is required only for a local containerized Airflow.
  set_env_value AIRFLOW_SOURCE_API_BRIDGE_ENABLED false
  # Tokens carry the browser-reachable issuer.  API-side key retrieval remains
  # on the private Compose network through OIDC_JWKS_URL below.
  set_env_value OIDC_ISSUER http://localhost:8081/realms/datariver
  set_env_value OIDC_JWKS_URL http://keycloak:8080/realms/datariver/protocol/openid-connect/certs
  set_env_value OIDC_PUBLIC_AUTHORITY http://localhost:8081/realms/datariver
  set_env_value OIDC_PUBLIC_ORIGIN http://localhost:8081
  set_env_value WORKSPACE_SELECTION_ENABLED false
  set_env_value REDIS_CACHE_URL redis://redis-cache:6379/0
  set_env_value REDIS_DELIVERY_URL redis://redis-delivery:6379/0
  set_env_value DATABASE_POOL_SIZE 4
  set_env_value DATABASE_POOL_MAX_OVERFLOW 0
  set_env_value WORKER_DATABASE_POOL_SIZE 1
  set_env_value WORKER_DATABASE_POOL_MAX_OVERFLOW 0
  set_env_value DATAHUB_MAX_CONCURRENCY 8
  set_env_value NEO4J_MAXIMUM_CONNECTION_POOL_SIZE 4
  set_env_value LOCAL_OLLAMA_CHAT_ENABLED false
  set_env_value LOCAL_OLLAMA_EMBEDDING_ENABLED false
  set_env_value LOCAL_LLAMA_CPP_RERANKER_ENABLED false
  # The separately verified AMD64 archive restores this local tag. The
  # immutable/container profile uses Docker DNS; a derived host-development
  # profile translates this endpoint to the loopback publication above.
  set_env_value NEO4J_IMAGE neo4j:2026.06.0
  set_env_value NEO4J_PROJECTION_ENABLED false
  set_env_value NEO4J_SOURCE_HOST_ENABLED false
  set_env_value NEO4J_URI bolt://neo4j:7687
  set_env_value NEO4J_ALLOWED_HOSTS neo4j
  set_env_value NEO4J_AUTH_SECRET_REF file:/run/secrets/neo4j_auth
  set_env_value KNOWLEDGE_PIPELINE_ENABLED false
  set_env_value KNOWLEDGE_SOURCE_WORKER_ENABLED false
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
chmod 0700 "$secrets_dir" "$keycloak_runtime_dir" "$identity_runtime_dir"
chmod 0444 "$secrets_dir"/* "$keycloak_runtime_dir/datariver-realm.json"
if [ -f "$demo_identity_state" ]; then
  chmod 0600 "$demo_identity_state"
fi
chmod 0644 "$retention_control_file"

echo "Bootstrap files created in $env_file. Keep the environment and secrets directory private and out of Git."
