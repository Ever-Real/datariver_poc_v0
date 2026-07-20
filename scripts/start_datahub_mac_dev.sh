#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
datahub_root="$root/runtime/datahub-v1.6.0"
datahub_commit="059a36c0b035a6057de00114ccac0ea9003d6bc2"
quickstart_compose="$datahub_root/docker/quickstart/docker-compose-without-neo4j-m1.quickstart.yml"
image_override="$root/infra/datahub/datahub-v1.6.0-mac-dev.images.yaml"
secrets_dir="$root/secrets"

if [ ! -e "$datahub_root" ]; then
  mkdir -p "$root/runtime"
  git clone --depth 1 --branch v1.6.0 \
    https://github.com/datahub-project/datahub.git "$datahub_root"
elif [ ! -d "$datahub_root/.git" ]; then
  echo "$datahub_root exists but is not an official DataHub source checkout." >&2
  exit 2
fi

if [ "$(git -C "$datahub_root" rev-parse HEAD 2>/dev/null || true)" != "$datahub_commit" ]; then
  echo "runtime/datahub-v1.6.0 must be the official v1.6.0 commit $datahub_commit." >&2
  exit 2
fi

for required in "$quickstart_compose" "$image_override"; do
  if [ ! -f "$required" ]; then
    echo "Missing DataHub Mac development prerequisite: $required" >&2
    exit 2
  fi
done

ensure_secret() {
  local name=$1
  local path="$secrets_dir/$name"
  mkdir -p "$secrets_dir"
  chmod 0700 "$secrets_dir"
  if [ ! -s "$path" ]; then
    umask 077
    openssl rand -base64 48 | tr -d '\n' > "$path"
  fi
  chmod 0600 "$path"
  cat "$path"
}

export DATAHUB_TOKEN_SERVICE_SIGNING_KEY="$(ensure_secret datahub_token_service_signing_key)"
export DATAHUB_TOKEN_SERVICE_SALT="$(ensure_secret datahub_token_service_salt)"

compose=(
  docker compose -p datahub
  -f "$quickstart_compose"
  -f "$image_override"
)

case "${1:-start}" in
  config)
    # Do not interpolate the locally generated token secrets into output.
    "${compose[@]}" config --no-interpolate --format json
    ;;
  start)
    # Pull quietly first: the full DataHub image set is large and verbose pull
    # progress obscures the actual compose health result on a first Mac setup.
    "${compose[@]}" pull --quiet
    "${compose[@]}" up -d --pull never --wait
    ;;
  stop)
    "${compose[@]}" stop
    ;;
  status)
    "${compose[@]}" ps --all
    ;;
  *)
    echo "Usage: $0 [config|start|stop|status]" >&2
    exit 2
    ;;
esac
