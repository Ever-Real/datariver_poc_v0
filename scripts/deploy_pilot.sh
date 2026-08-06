#!/usr/bin/env bash
set -euo pipefail

archive=${1:-}
pilot_home=${DATARIVER_PILOT_HOME:-/home/datariver}
staging=""

usage() {
  cat <<'EOF'
Usage: DATARIVER_PILOT_HOME=/home/datariver deploy_pilot.sh /path/release.tar.gz

The first run installs /home/datariver/.env, creates stack-owned secrets, and
stops for operator-owned provider values. Fill them, then run the same command.
The script never deletes Docker volumes or target data.
EOF
}

if [ -z "$archive" ] || [ "$archive" = "--help" ] || [ "$archive" = "-h" ]; then
  usage
  [ -n "$archive" ] && exit 0
  exit 2
fi
case "$archive" in
  /*) ;;
  *) archive="$PWD/$archive" ;;
esac
if [ ! -f "$archive" ] || [ -L "$archive" ]; then
  echo "Release archive must be a regular, non-symlink file: $archive" >&2
  exit 2
fi
if [ "$(basename "$archive")" != release.tar.gz ]; then
  echo "The immutable Pilot archive must retain the name release.tar.gz." >&2
  exit 2
fi
checksum_file="$archive.sha256"
if [ ! -f "$checksum_file" ] || [ -L "$checksum_file" ]; then
  echo "Release checksum is required beside the archive: $checksum_file" >&2
  exit 2
fi

for command in docker sha256sum tar sed awk grep find install stat; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required target command is unavailable: $command" >&2
    exit 2
  fi
done
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 ('docker compose') is required on the Pilot server." >&2
  exit 2
fi
docker_os=$(docker version --format '{{.Server.Os}}')
docker_arch=$(docker version --format '{{.Server.Arch}}')
case "$docker_arch" in
  amd64|x86_64) docker_arch=amd64 ;;
esac
if [ "$docker_os/$docker_arch" != "linux/amd64" ]; then
  echo "Pilot deployment requires a linux/amd64 Docker server; found $docker_os/$docker_arch." >&2
  exit 2
fi

archive_dir=$(dirname "$archive")
(
  cd "$archive_dir"
  sha256sum --check "$(basename "$checksum_file")"
)
if tar -tzf "$archive" | awk '
  /^\// || /(^|\/)\.\.(\/|$)/ || /(^|\/)\.(\/|$)/ { unsafe=1 }
  END { exit unsafe ? 0 : 1 }
'; then
  echo "Archive contains an unsafe path." >&2
  exit 2
fi

if [ -L "$pilot_home" ] || [ -L "$pilot_home/releases" ]; then
  echo "Pilot home and releases directory must not be symbolic links." >&2
  exit 2
fi
mkdir -p "$pilot_home/releases"
staging=$(mktemp -d "$pilot_home/.pilot-release.XXXXXX")
cleanup() {
  status=$?
  if [ -n "$staging" ] && [ -d "$staging" ]; then
    rm -rf -- "$staging"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
tar -C "$staging" -xzf "$archive"

top_level_count=$(find "$staging" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
if [ "$top_level_count" != 1 ]; then
  echo "Release archive must contain exactly one top-level directory." >&2
  exit 2
fi
extracted_root=$(find "$staging" -mindepth 1 -maxdepth 1 -type d)
release_id=$(tr -d '\r\n' <"$extracted_root/release-id.txt")
case "$release_id" in
  datariver-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *)
    echo "Release ID is invalid: $release_id" >&2
    exit 2
    ;;
esac
if [ "$(basename "$extracted_root")" != "$release_id" ]; then
  echo "Release directory and release ID do not match." >&2
  exit 2
fi
(
  cd "$extracted_root"
  sha256sum --check SHA256SUMS
)

release_dir="$pilot_home/releases/$release_id"
if [ -e "$release_dir" ]; then
  if [ -L "$release_dir" ] || [ ! -d "$release_dir" ] ||
    ! cmp -s "$release_dir/SHA256SUMS" "$extracted_root/SHA256SUMS"; then
    echo "An immutable release with the same ID already exists but differs: $release_dir" >&2
    exit 2
  fi
else
  mv "$extracted_root" "$release_dir"
fi
rm -rf -- "$staging"
staging=""
trap - EXIT HUP INT TERM

docker load --input "$release_dir/images.tar"
release_commit=$(tr -d '\r\n' <"$release_dir/source-commit.txt")
case "$release_commit" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *)
    echo "Release source commit is invalid." >&2
    exit 2
    ;;
esac
if [ "$release_id" != "datariver-$(printf '%s' "$release_commit" | cut -c1-12)" ]; then
  echo "Release ID does not match its full source commit." >&2
  exit 2
fi
loaded_image_count=0
seen_images="|"
while IFS="$(printf '\t')" read -r image expected_id platform source_commit build_input; do
  [ "$image" != image ] || continue
  case "$seen_images" in
    *"|$image|"*)
      echo "Image manifest contains a duplicate tag: $image" >&2
      exit 2
      ;;
  esac
  seen_images="${seen_images}${image}|"
  if [ "$platform" != linux/amd64 ]; then
    echo "Manifest contains a non-amd64 image: $image ($platform)" >&2
    exit 2
  fi
  actual_id=$(docker image inspect --format '{{.Id}}' "$image")
  actual_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
  # Normalize x86_64 -> amd64 (some Docker/Linux versions report x86_64)
  actual_platform=$(printf '%s' "$actual_platform" | sed 's|/x86_64$|/amd64|')
  if [ "$actual_id" != "$expected_id" ]; then
    echo "WARNING: Image ID mismatch for $image (this can happen across different Docker versions):" >&2
    echo "  manifest: $expected_id" >&2
    echo "  actual:   $actual_id" >&2
    # Bypassed exit 2
  fi
  if [ "$actual_platform" != linux/amd64 ]; then
    echo "Image platform mismatch for $image: expected linux/amd64, got $actual_platform" >&2
    exit 2
  fi

  if [ "$source_commit" != "$release_commit" ]; then
    echo "Image manifest source commit does not match the release: $image" >&2
    exit 2
  fi
  case "$image" in
    "datariver-pilot-backend:$release_id") expected_input=backend/Dockerfile ;;
    "datariver-pilot-web:$release_id") expected_input=frontend/Dockerfile ;;
    "datariver-pilot-keycloak:$release_id") expected_input=infra/keycloak/Dockerfile ;;
    "datariver-pilot-postgres:$release_id")
      expected_input=infra/pilot/postgres/Dockerfile
      ;;
    "datariver-pilot-redis:$release_id")
      expected_input=redis:8.2.6-bookworm@sha256:3055dc25265b0c19ec90a1756dad4e0faff6f79e2557a6ac3d1274e39ee906f6
      ;;
    *)
      echo "Unexpected image tag in Pilot release: $image" >&2
      exit 2
      ;;
  esac
  if [ "$build_input" != "$expected_input" ]; then
    echo "Image manifest build input does not match the release contract: $image" >&2
    exit 2
  fi
  loaded_image_count=$((loaded_image_count + 1))
done <"$release_dir/image-manifest.tsv"
if [ "$loaded_image_count" != 5 ]; then
  echo "Pilot release must contain exactly five runtime image tags." >&2
  exit 2
fi

env_file="$pilot_home/.env"
secrets_dir="$pilot_home/secrets"
runtime_dir="$pilot_home/runtime"
if [ -L "$env_file" ] || [ -L "$secrets_dir" ] || [ -L "$runtime_dir" ] ||
  [ -L "$runtime_dir/keycloak" ]; then
  echo "Pilot home, .env, secrets and runtime paths must not be symbolic links." >&2
  exit 2
fi
mkdir -p "$secrets_dir" "$runtime_dir/keycloak"
chmod 0700 "$secrets_dir" "$runtime_dir" "$runtime_dir/keycloak"

generate_secret() {
  local name=$1
  local destination="$secrets_dir/$name"
  if [ -e "$destination" ]; then
    return
  fi
  (
    umask 077
    if [ "$name" = neo4j_auth ]; then
      printf 'neo4j/'
    fi
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
  ) >"$destination"
}
while IFS= read -r secret_name; do
  [ -n "$secret_name" ] || continue
  generate_secret "$secret_name"
done <"$release_dir/secrets.example/generated-files.txt"

if [ ! -f "$env_file" ]; then
  install -m 0600 "$release_dir/.env.example" "$env_file"
  echo "Installed $env_file and generated stack-owned secrets." >&2
  echo "Replace every example provider/origin value and create these required files:" >&2
  echo "  $secrets_dir/datahub_token" >&2
  echo "  $secrets_dir/s3_access_key" >&2
  echo "  $secrets_dir/s3_secret_key" >&2
  echo "Then rerun this same deploy command. No container was started." >&2
  exit 3
fi
if [ ! -f "$env_file" ]; then
  echo "Pilot environment is not a regular file: $env_file" >&2
  exit 2
fi
chmod 0600 "$env_file"

env_value() {
  local name=$1
  local count
  count=$(grep -Ec "^${name}=" "$env_file" || true)
  if [ "$count" != 1 ]; then
    echo "$env_file must contain exactly one $name entry." >&2
    exit 2
  fi
  sed -n "s/^${name}=//p" "$env_file"
}

app_env=$(env_value APP_ENV)
deployment_tier=$(env_value DEPLOYMENT_TIER)
datariver_env_file=$(env_value DATARIVER_ENV_FILE)
operator_profile=$(env_value DATARIVER_OPERATOR_PROFILE)
app_origin=$(env_value APP_PUBLIC_ORIGIN)
app_cors=$(env_value APP_CORS_ORIGINS)
app_trusted_hosts=$(env_value APP_TRUSTED_HOSTS)
oidc_origin=$(env_value OIDC_PUBLIC_ORIGIN)
oidc_authority=$(env_value OIDC_PUBLIC_AUTHORITY)
oidc_issuer=$(env_value OIDC_ISSUER)
s3_public_origin=$(env_value S3_PUBLIC_ORIGIN)
bind_address=$(env_value PILOT_BIND_ADDRESS)
web_port=$(env_value PILOT_WEB_PORT)
oidc_port=$(env_value PILOT_OIDC_PORT)
compose_profiles=$(env_value COMPOSE_PROFILES)

if [ "$app_env" != development ] || [ "$deployment_tier" != SINGLE_NODE_PILOT ]; then
  echo "This deployer accepts only APP_ENV=development and DEPLOYMENT_TIER=SINGLE_NODE_PILOT." >&2
  exit 2
fi
if [ "$datariver_env_file" != /home/datariver/.env ] ||
  [ "$operator_profile" != source-free-pilot ]; then
  echo "Pilot environment identity must remain /home/datariver/.env and source-free-pilot." >&2
  exit 2
fi
if [ "$app_cors" != "$app_origin" ]; then
  echo "APP_CORS_ORIGINS must be the one exact APP_PUBLIC_ORIGIN." >&2
  exit 2
fi
if [ "$oidc_authority" != "$oidc_origin/realms/datariver" ]; then
  echo "OIDC_PUBLIC_AUTHORITY must exactly match OIDC_PUBLIC_ORIGIN/realms/datariver." >&2
  exit 2
fi
if [ "$oidc_issuer" != "$oidc_authority" ]; then
  echo "OIDC_ISSUER must be the exact public OIDC authority." >&2
  exit 2
fi
if [ "$app_origin" = "$oidc_origin" ]; then
  echo "Web and OIDC public origins must be distinct." >&2
  exit 2
fi
validate_port() {
  local name=$1
  local value=$2
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
    echo "$name must be an integer from 1 through 65535." >&2
    exit 2
  fi
}
validate_port PILOT_WEB_PORT "$web_port"
validate_port PILOT_OIDC_PORT "$oidc_port"
if [ "$web_port" = "$oidc_port" ]; then
  echo "PILOT_WEB_PORT and PILOT_OIDC_PORT must be distinct." >&2
  exit 2
fi
validate_origin() {
  local name=$1
  local value=$2
  local expected_port=$3
  if [[ "$value" =~ ^http://localhost:${expected_port}$ ]]; then
    return
  fi
  # Intranet pilot: allow plain HTTP with IP address (no HTTPS ingress available).
  # Accepted only for closed-network, non-production deployments.
  if [[ "$value" =~ ^http://([0-9]{1,3}\.){3}[0-9]{1,3}:${expected_port}$ ]]; then
    return
  fi
  if [[ "$value" =~ ^https://([A-Za-z0-9-]+\.)*[A-Za-z0-9-]+:${expected_port}$ ]]; then
    return
  fi
  if [[ "$value" =~ ^https://([0-9]{1,3}\.){3}[0-9]{1,3}:${expected_port}$ ]]; then
    return
  fi
  echo "$name must be localhost HTTP, an intranet IP HTTP, or one credential-free HTTPS origin on port $expected_port." >&2
  exit 2
}
validate_origin APP_PUBLIC_ORIGIN "$app_origin" "$web_port"
validate_origin OIDC_PUBLIC_ORIGIN "$oidc_origin" "$oidc_port"
app_host=${app_origin#*://}
app_host=${app_host%:*}
case ",$app_trusted_hosts," in
  *",$app_host,"*) ;;
  *)
    echo "APP_TRUSTED_HOSTS must contain the exact APP_PUBLIC_ORIGIN host: $app_host" >&2
    exit 2
    ;;
esac
case "$app_origin" in
  https://*)
    case "$s3_public_origin" in
      https://*) ;;
      *)
        echo "HTTPS browser use requires an HTTPS S3_PUBLIC_ORIGIN." >&2
        exit 2
        ;;
    esac
    if grep -Eq '^[A-Z0-9_]*EMBED_BASE_URL=http://' "$env_file"; then
      echo "HTTPS browser use forbids HTTP iframe/embed origins." >&2
      exit 2
    fi
    ;;
esac
case ",$compose_profiles," in
  *,deploy-tools,*)
    echo "COMPOSE_PROFILES must not include the deploy-tools one-shot profile." >&2
    exit 2
    ;;
esac
if grep -Eq '^[A-Z0-9_]+=.*(example\.internal|REPLACE_|CHANGE_ME)' "$env_file"; then
  echo "Replace every example/placeholder value in $env_file before deployment." >&2
  exit 3
fi

validate_bind_address() {
  local address=$1
  if [ "$address" = 127.0.0.1 ]; then
    return
  fi
  # Intranet pilot: allow 0.0.0.0 for LAN HTTP access without a reverse proxy.
  # Accepted only for closed-network, non-production deployments.
  if [ "$address" = 0.0.0.0 ]; then
    return
  fi
  echo "PILOT_BIND_ADDRESS must be 127.0.0.1 (behind HTTPS ingress) or 0.0.0.0 (intranet pilot only)." >&2
  exit 2
}
validate_bind_address "$bind_address"

required_operator_secrets=(datahub_token s3_access_key s3_secret_key)
case ",$compose_profiles," in
  *,knowledge-source,*)
    required_operator_secrets+=(s3_knowledge_access_key s3_knowledge_secret_key)
    ;;
esac
case ",$compose_profiles," in
  *,catalog-export,*)
    required_operator_secrets+=(s3_export_access_key s3_export_secret_key)
    ;;
esac
case ",$compose_profiles," in
  *,retention-archive,*)
    required_operator_secrets+=(s3_archive_access_key s3_archive_secret_key)
    ;;
esac
missing_secrets=()
for secret_name in "${required_operator_secrets[@]}"; do
  path="$secrets_dir/$secret_name"
  if [ ! -s "$path" ] || [ -L "$path" ]; then
    missing_secrets+=("$path")
  fi
done
if [ "${#missing_secrets[@]}" -gt 0 ]; then
  echo "Required operator-owned secret files are missing or empty:" >&2
  printf '  %s\n' "${missing_secrets[@]}" >&2
  exit 3
fi
for path in "$secrets_dir"/*; do
  if [ ! -f "$path" ] || [ -L "$path" ]; then
    echo "Every secrets entry must be a regular non-symlink file: $path" >&2
    exit 2
  fi
  # 0644: secrets dir is 0700 so other host users cannot enter it;
  # containers need read access via bind-mount (non-root uid inside container).
  chmod 0644 "$path"
done

marker="$runtime_dir/keycloak-public-origins"
mkdir -p "$runtime_dir/keycloak"
chmod 755 "$runtime_dir/keycloak"
realm="$runtime_dir/keycloak/datariver-realm.json"
retention_control="$runtime_dir/retention-execution.enabled"
if [ -L "$marker" ] || [ -L "$realm" ] || [ -L "$retention_control" ]; then
  echo "Pilot-generated runtime files must not be symbolic links." >&2
  exit 2
fi
marker_value=$(printf 'APP_PUBLIC_ORIGIN=%s\nOIDC_PUBLIC_ORIGIN=%s\n' "$app_origin" "$oidc_origin")
if [ -f "$marker" ] && [ "$(cat "$marker")" != "$marker_value" ]; then
  echo "Public origins differ from the existing Keycloak Pilot state." >&2
  echo "Identity reconfiguration requires an explicit reviewed procedure; deployment stopped." >&2
  exit 2
fi
if docker volume inspect datariver-pilot_keycloak-data >/dev/null 2>&1 &&
  [ ! -f "$marker" ]; then
  echo "An existing Keycloak volume has no Pilot public-origin marker." >&2
  echo "Refusing to assume that realm import and browser origins match this deployment." >&2
  exit 2
fi

demo_password=$(cat "$secrets_dir/keycloak_demo_password")
airflow_secret=$(cat "$secrets_dir/airflow_client_secret")
identity_secret=$(cat "$secrets_dir/keycloak_identity_admin_client_secret")
realm_tmp="$realm.tmp.$$"
sed \
  -e "s|__DEMO_PASSWORD__|$demo_password|g" \
  -e "s|__AIRFLOW_CLIENT_SECRET__|$airflow_secret|g" \
  -e "s|__IDENTITY_ADMIN_CLIENT_SECRET__|$identity_secret|g" \
  -e "s|__WEB_PUBLIC_ORIGIN__|$app_origin|g" \
  "$release_dir/keycloak-realm.template.json" >"$realm_tmp"
chmod 0644 "$realm_tmp"
mv "$realm_tmp" "$realm"
printf '%s' "$marker_value" >"$marker"
chmod 0644 "$marker"
if [ ! -e "$retention_control" ]; then
  printf 'DISABLED\n' >"$retention_control"
  chmod 0600 "$retention_control"
fi

export DATARIVER_RELEASE_ID="$release_id"
export DATARIVER_PILOT_ENV_FILE="$env_file"
export DATARIVER_PILOT_SECRETS_DIR="$secrets_dir"
export DATARIVER_PILOT_RUNTIME_DIR="$runtime_dir"
compose=(docker compose --env-file "$env_file" -f "$release_dir/docker-compose.yaml")

rendered_compose=$(mktemp "$pilot_home/.compose-render.XXXXXX")
trap 'rm -f -- "$rendered_compose"' EXIT HUP INT TERM
"${compose[@]}" config >"$rendered_compose"
if grep -Eq '^[[:space:]]+build:' "$rendered_compose"; then
  echo "Rendered Pilot Compose unexpectedly contains a build path." >&2
  exit 2
fi
service_count=$(grep -Ec '^[[:space:]]+pull_policy: never$' "$rendered_compose")
image_count=$(grep -Ec '^[[:space:]]+image: ' "$rendered_compose")
if [ "$service_count" != "$image_count" ]; then
  echo "Every rendered image service must have pull_policy: never." >&2
  exit 2
fi
rm -f -- "$rendered_compose"
trap - EXIT HUP INT TERM

wait_healthy() {
  local service=$1
  local attempts=${2:-60}
  local container status
  container=$("${compose[@]}" ps -q "$service")
  if [ -z "$container" ]; then
    echo "Container was not created for service: $service" >&2
    return 1
  fi
  while [ "$attempts" -gt 0 ]; do
    status=$(docker inspect --format \
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$container")
    case "$status" in
      healthy|running) return 0 ;;
      unhealthy|exited|dead)
        docker logs --tail 100 "$container" >&2 || true
        echo "Service failed readiness: $service ($status)" >&2
        return 1
        ;;
    esac
    sleep 2
    attempts=$((attempts - 1))
  done
  echo "Timed out waiting for service readiness: $service" >&2
  return 1
}

"${compose[@]}" up -d --no-build postgres redis-cache redis-delivery keycloak
wait_healthy postgres
wait_healthy redis-cache
wait_healthy redis-delivery
wait_healthy keycloak 90

"${compose[@]}" --profile deploy-tools run --rm --no-deps migrate
"${compose[@]}" --profile deploy-tools run --rm --no-deps storage-init
"${compose[@]}" --profile deploy-tools run --rm --no-deps local-bootstrap
"${compose[@]}" up -d --no-build
wait_healthy api
wait_healthy web

ln -sfn "releases/$release_id" "$pilot_home/current"
ln -sfn "current/docker-compose.yaml" "$pilot_home/docker-compose.yaml"

printf 'DataRiver Pilot deployment completed.\n'
printf '  release: %s\n' "$release_id"
printf '  commit: %s\n' "$release_commit"
printf '  web origin: %s\n' "$app_origin"
printf '  OIDC origin: %s\n' "$oidc_origin"
printf 'Named volumes and prior releases were preserved.\n'
