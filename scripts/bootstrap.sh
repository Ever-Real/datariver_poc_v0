#!/usr/bin/env sh
set -eu

datahub_token=
datahub_base_url=
host_development=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --host-development)
      host_development=true
      ;;
    --datahub-base-url)
      shift
      [ "$#" -gt 0 ] || { echo "--datahub-base-url requires a value" >&2; exit 2; }
      datahub_base_url=$1
      ;;
    *)
      [ -z "$datahub_token" ] || { echo "unexpected argument: $1" >&2; exit 2; }
      datahub_token=$1
      ;;
  esac
  shift
done

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
secrets_dir="$root/secrets"
keycloak_runtime_dir="$root/runtime/keycloak"
mkdir -p "$secrets_dir"
mkdir -p "$keycloak_runtime_dir"
umask 077

for existing_file in "$secrets_dir"/* "$keycloak_runtime_dir"/datariver-realm.json; do
  if [ -f "$existing_file" ]; then
    chmod 0600 "$existing_file"
  fi
done

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

[ -f "$root/.env" ] || cp "$root/.env.example" "$root/.env"

ensure_random_secret postgres_password 32
ensure_random_secret postgres_app_password 32
ensure_random_secret postgres_relay_password 32
ensure_random_secret postgres_upload_password 32
ensure_random_secret postgres_governance_password 32
ensure_random_secret postgres_bootstrap_password 32
ensure_random_secret keycloak_db_password 32
ensure_random_secret airflow_db_password 32
ensure_random_secret airflow_api_secret 48
ensure_random_secret airflow_client_secret 32
ensure_random_secret airflow_admin_password 24
ensure_random_secret keycloak_demo_password 18
ensure_random_secret keycloak_admin_password 24
ensure_random_secret valkey_cache_password 32
ensure_random_secret valkey_queue_password 32
if [ -n "$datahub_token" ]; then
  printf '%s' "$datahub_token" > "$secrets_dir/datahub_token"
elif [ ! -s "$secrets_dir/datahub_token" ]; then
  echo "datahub token is required when secrets/datahub_token does not exist" >&2
  exit 2
fi
if [ ! -s "$secrets_dir/s3_access_key" ]; then
  random_secret 18 | tr '/+' 'AB' | tr -d '=' > "$secrets_dir/s3_access_key"
fi
ensure_random_secret s3_secret_key 36
s3_access=$(cat "$secrets_dir/s3_access_key")
s3_secret=$(cat "$secrets_dir/s3_secret_key")

printf '{"identities":[{"name":"datariver","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List","Tagging"]}]}' \
  "$s3_access" "$s3_secret" > "$secrets_dir/seaweed_s3_config.json"

demo_password=$(cat "$secrets_dir/keycloak_demo_password")
airflow_client_secret=$(cat "$secrets_dir/airflow_client_secret")
escaped_demo_password=$(printf '%s' "$demo_password" | sed 's/[\/&]/\\&/g')
escaped_airflow_client_secret=$(printf '%s' "$airflow_client_secret" | sed 's/[\/&]/\\&/g')
web_public_origin=http://localhost:8080
if [ "$host_development" = true ]; then
  web_public_origin=http://localhost:5173
fi
escaped_web_public_origin=$(printf '%s' "$web_public_origin" | sed 's/[\/&]/\\&/g')
sed -e "s/__DEMO_PASSWORD__/$escaped_demo_password/g" \
  -e "s/__AIRFLOW_CLIENT_SECRET__/$escaped_airflow_client_secret/g" \
  -e "s/__WEB_PUBLIC_ORIGIN__/$escaped_web_public_origin/g" \
  "$root/infra/keycloak/datariver-realm.template.json" \
  > "$keycloak_runtime_dir/datariver-realm.json"

set_env_value() {
  name=$1
  value=$2
  temp_file="$root/.env.tmp.$$"
  if grep -q "^${name}=" "$root/.env"; then
    sed "s|^${name}=.*|${name}=${value}|" "$root/.env" > "$temp_file"
  else
    cp "$root/.env" "$temp_file"
    printf '%s=%s\n' "$name" "$value" >> "$temp_file"
  fi
  mv "$temp_file" "$root/.env"
}

if [ "$host_development" = true ]; then
  set_env_value APP_PUBLIC_ORIGIN "$web_public_origin"
  set_env_value APP_CORS_ORIGINS "$web_public_origin"
  set_env_value POSTGRES_PORT 5432
  set_env_value VALKEY_CACHE_PORT 6379
  set_env_value VALKEY_QUEUE_PORT 6380
  set_env_value KEYCLOAK_PORT 18081
  set_env_value APISIX_PORT 9080
  set_env_value OIDC_ISSUER http://localhost:18081/realms/datariver
  set_env_value OIDC_PUBLIC_AUTHORITY http://localhost:18081/realms/datariver
  set_env_value OIDC_PUBLIC_ORIGIN http://localhost:18081
fi
if [ -n "$datahub_base_url" ]; then
  set_env_value DATAHUB_BASE_URL "$datahub_base_url"
fi

# File-based Compose secrets are bind mounts, so container users with different
# UIDs need read permission. Host access remains restricted by the 0700 parents.
chmod 0700 "$secrets_dir" "$keycloak_runtime_dir"
chmod 0444 "$secrets_dir"/* "$keycloak_runtime_dir/datariver-realm.json"

echo "Bootstrap files created. Keep the secrets directory private and out of Git."
