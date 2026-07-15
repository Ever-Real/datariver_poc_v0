#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: ./scripts/bootstrap.sh <datahub-token>" >&2
  exit 2
fi

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
printf '%s' "$1" > "$secrets_dir/datahub_token"
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
sed -e "s/__DEMO_PASSWORD__/$escaped_demo_password/g" \
  -e "s/__AIRFLOW_CLIENT_SECRET__/$escaped_airflow_client_secret/g" \
  "$root/infra/keycloak/datariver-realm.template.json" \
  > "$keycloak_runtime_dir/datariver-realm.json"

# File-based Compose secrets are bind mounts, so container users with different
# UIDs need read permission. Host access remains restricted by the 0700 parents.
chmod 0700 "$secrets_dir" "$keycloak_runtime_dir"
chmod 0444 "$secrets_dir"/* "$keycloak_runtime_dir/datariver-realm.json"

echo "Bootstrap files created. Keep the secrets directory private and out of Git."
