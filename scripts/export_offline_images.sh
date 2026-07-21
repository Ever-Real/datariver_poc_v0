#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$root/docker_imgs"
include_datahub_mac_dev=false
include_observability=false
build_datariver=false
target_platform=""
backup_file=""
cross_platform=false

usage() {
  cat <<'EOF'
Usage: scripts/export_offline_images.sh [options]

Export Docker images already present on this host into architecture-specific tar bundles.
The output directory is ignored by Git and contains no source configuration or secrets.

Options:
  --output DIR                 Output directory (default: <repo>/docker_imgs).
  --platform linux/ARCH        Export linux/arm64 (default) or linux/amd64 images.
                               A non-native target is built/pulled through Buildx-compatible
                               Docker Desktop and restores every pre-existing local tag.
  --build-datariver            Build all checked-in DataRiver images before export.
  --include-datahub-mac-dev    Include the local-only DataHub v1.6.0 Apple-Silicon bundle.
  --include-observability      Include the optional Single-node Pilot telemetry images.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      shift
      output_dir=${1:?--output requires a directory}
      ;;
    --platform)
      shift
      target_platform=${1:?--platform requires linux/arm64 or linux/amd64}
      ;;
    --build-datariver)
      build_datariver=true
      ;;
    --include-datahub-mac-dev)
      include_datahub_mac_dev=true
      ;;
    --include-observability)
      include_observability=true
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

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required." >&2
  exit 2
fi

architecture=$(docker version --format '{{.Server.Arch}}')
os=$(docker version --format '{{.Server.Os}}')
if [ "$os" != linux ]; then
  echo "Only Linux OCI images can be exported; Docker daemon reports $os/$architecture." >&2
  exit 2
fi

target_os=$os
target_architecture=$architecture
if [ -n "$target_platform" ]; then
  case "$target_platform" in
    linux/arm64|linux/amd64)
      target_os=${target_platform%/*}
      target_architecture=${target_platform#*/}
      ;;
    *)
      echo "Unsupported --platform $target_platform; use linux/arm64 or linux/amd64." >&2
      exit 2
      ;;
  esac
fi
target_platform="$target_os/$target_architecture"

if [ "$target_platform" != "$os/$architecture" ]; then
  cross_platform=true
  if [ "$build_datariver" != true ]; then
    echo "Cross-platform exports require --build-datariver so checked-in images are built for $target_platform." >&2
    exit 2
  fi
  if ! docker buildx inspect >/dev/null 2>&1; then
    echo "A Buildx builder capable of $target_platform is required for a cross-platform export." >&2
    exit 2
  fi
  if [ "$include_datahub_mac_dev" = true ]; then
    echo "The checked-in DataHub development bundle is arm64-only and cannot be included in a $target_platform export." >&2
    exit 2
  fi
fi

platform_images=(
  postgres:17.10-bookworm
  valkey/valkey:9.1.0-alpine
  chrislusf/seaweedfs:4.39_full
  neo4j:2026.06.0
  datariver-next-migrate:latest
  datariver-next-storage-init:latest
  datariver-next-local-bootstrap:latest
  datariver-next-semiconductor-seed:latest
  datariver-next-api:latest
  datariver-next-outbox-relay:latest
  datariver-next-upload-worker:latest
  datariver-next-upload-validation-worker:latest
  datariver-next-governance-apply-worker:latest
  datariver-next-catalog-export-worker:latest
  datariver-next-web:latest
  datariver-keycloak:26.7.0
  datariver-airflow:3.3.0-python3.12
  datariver-apisix:3.17.0-debian
)

external_platform_images=(
  postgres:17.10-bookworm
  valkey/valkey:9.1.0-alpine
  chrislusf/seaweedfs:4.39_full
  neo4j:2026.06.0
)

observability_images=(
  otel/opentelemetry-collector-contrib:0.153.0
  prom/prometheus:v3.12.0
  grafana/grafana:13.1.0
  prom/alertmanager:v0.32.1
  grafana/tempo:2.10.5
  grafana/loki:3.7.2
)

backup_existing_tag() {
  local image=$1
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    return
  fi
  local safe_image backup
  safe_image=$(printf '%s' "$image" | tr '/:' '__')
  backup="datariver-offline-export-backup:${safe_image}-${target_architecture}-$$"
  docker image tag "$image" "$backup"
  printf '%s\t%s\n' "$image" "$backup" >>"$backup_file"
}

restore_backed_up_tags() {
  if [ -z "$backup_file" ] || [ ! -f "$backup_file" ]; then
    return
  fi
  while IFS="$(printf '\t')" read -r original backup; do
    [ -n "$original" ] || continue
    docker image tag "$backup" "$original" || true
    docker image rm "$backup" >/dev/null 2>&1 || true
  done <"$backup_file"
  rm -f "$backup_file"
  backup_file=""
}

cleanup_cross_platform_export() {
  status=$?
  if [ "$cross_platform" = true ]; then
    restore_backed_up_tags
  fi
  exit "$status"
}

if [ "$cross_platform" = true ]; then
  backup_file=$(mktemp "${TMPDIR:-/tmp}/datariver-offline-images.XXXXXX")
  trap cleanup_cross_platform_export EXIT HUP INT TERM
  for image in "${platform_images[@]}"; do
    backup_existing_tag "$image"
  done
  if [ "$include_observability" = true ]; then
    for image in "${observability_images[@]}"; do
      backup_existing_tag "$image"
    done
  fi
fi

read_dotenv_value() {
  local key=$1
  local fallback=$2
  local value=${!key:-}
  if [ -z "$value" ] && [ -f "$root/.env" ]; then
    value=$(awk -F= -v requested_key="$key" '
      $1 == requested_key {
        value = substr($0, length(requested_key) + 2)
        gsub(/^"|"$/, "", value)
        print value
        exit
      }
    ' "$root/.env")
  fi
  if [ -z "$value" ]; then
    value=$fallback
  fi
  printf '%s' "$value"
}

build_cross_platform_images() {
  local backend_image
  docker buildx build \
    --platform "$target_platform" \
    --load \
    --file "$root/backend/Dockerfile" \
    --tag datariver-next-api:latest \
    "$root"
  for backend_image in \
    datariver-next-migrate:latest \
    datariver-next-storage-init:latest \
    datariver-next-local-bootstrap:latest \
    datariver-next-semiconductor-seed:latest \
    datariver-next-outbox-relay:latest \
    datariver-next-upload-worker:latest \
    datariver-next-upload-validation-worker:latest \
    datariver-next-governance-apply-worker:latest \
    datariver-next-catalog-export-worker:latest; do
    docker image tag datariver-next-api:latest "$backend_image"
  done

  docker buildx build \
    --platform "$target_platform" \
    --load \
    --file "$root/frontend/Dockerfile" \
    --tag datariver-next-web:latest \
    --build-arg VITE_API_BASE_URL=/api/v1 \
    --build-arg "VITE_OIDC_AUTHORITY=$(read_dotenv_value OIDC_PUBLIC_AUTHORITY http://localhost:8081/realms/datariver)" \
    --build-arg "VITE_OIDC_CLIENT_ID=$(read_dotenv_value OIDC_CLIENT_ID datariver-web)" \
    --build-arg "VITE_OIDC_REDIRECT_URI=$(read_dotenv_value APP_PUBLIC_ORIGIN http://localhost:8080)" \
    --build-arg "VITE_OIDC_HIGH_ASSURANCE_ACR=$(read_dotenv_value OIDC_STEP_UP_ACR 2)" \
    --build-arg "VITE_OIDC_PASSWORD_REAUTH_ACR=$(read_dotenv_value OIDC_PASSWORD_REAUTH_ACR 1)" \
    "$root"

  docker buildx build \
    --platform "$target_platform" \
    --load \
    --file "$root/infra/keycloak/Dockerfile" \
    --tag datariver-keycloak:26.7.0 \
    "$root"
  docker buildx build \
    --platform "$target_platform" \
    --load \
    --file "$root/infra/airflow/Dockerfile" \
    --tag datariver-airflow:3.3.0-python3.12 \
    "$root"
  docker buildx build \
    --platform "$target_platform" \
    --load \
    --tag datariver-apisix:3.17.0-debian \
    "$root/infra/apisix"
}

materialize_cross_platform_images() {
  if [ "$cross_platform" != true ]; then
    return
  fi
  local temporary_dir dockerfile image
  temporary_dir=$(mktemp -d "${TMPDIR:-/tmp}/datariver-external-image.XXXXXX")
  dockerfile="$temporary_dir/Dockerfile"
  printf '%s\n' 'ARG BASE_IMAGE' 'FROM --platform=$TARGETPLATFORM ${BASE_IMAGE}' >"$dockerfile"
  for image in "$@"; do
    docker buildx build \
      --platform "$target_platform" \
      --load \
      --build-arg "BASE_IMAGE=$image" \
      --file "$dockerfile" \
      --tag "$image" \
      "$temporary_dir"
  done
  rm -rf "$temporary_dir"
}

if [ "$build_datariver" = true ]; then
  if [ "$cross_platform" = true ]; then
    build_cross_platform_images
  else
    docker compose \
    -f "$root/compose.yaml" \
    -f "$root/compose.identity.yaml" \
    -f "$root/compose.airflow.yaml" \
    -f "$root/compose.gateway.yaml" \
    build \
    migrate storage-init local-bootstrap semiconductor-seed api outbox-relay \
    upload-worker upload-validation-worker governance-apply-worker \
    catalog-export-worker web keycloak airflow-api-server apisix
  fi
fi

mkdir -p "$output_dir"

require_image() {
  local image=$1
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Required image is absent: $image" >&2
    echo "Build or pull it on a connected staging host, then rerun this command." >&2
    exit 2
  fi
  local platform
  platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
  if [ "$platform" != "$target_platform" ]; then
    echo "Image $image is $platform, but the requested platform is $target_platform." >&2
    exit 2
  fi
}

write_checksum() {
  local filename=$1
  (
    cd "$output_dir"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum "$filename" >"$filename.sha256"
    else
      shasum -a 256 "$filename" >"$filename.sha256"
    fi
  )
}

write_manifest() {
  local label=$1
  shift
  local manifest="$output_dir/$label.manifest.tsv"
  {
    printf 'image\timage_id\trepository_digests\tplatform\n'
    local image
    for image in "$@"; do
      printf '%s\t%s\t%s\t%s\n' \
        "$image" \
        "$(docker image inspect --format '{{.Id}}' "$image")" \
        "$(docker image inspect --format '{{join .RepoDigests ","}}' "$image")" \
        "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")"
    done
  } >"$manifest"
  write_checksum "$(basename "$manifest")"
}

save_bundle() {
  local label=$1
  shift
  local image
  for image in "$@"; do
    require_image "$image"
  done
  local tar_name="$label.tar"
  local temporary="$output_dir/$tar_name.partial"
  docker image save --output "$temporary" "$@"
  mv "$temporary" "$output_dir/$tar_name"
  write_checksum "$tar_name"
  write_manifest "$label" "$@"
  printf 'Created %s\n' "$output_dir/$tar_name"
}

materialize_cross_platform_images "${external_platform_images[@]}"
save_bundle "datariver-platform-$target_architecture" "${platform_images[@]}"

if [ "$include_datahub_mac_dev" = true ]; then
  if [ "$architecture" != arm64 ]; then
    echo "The checked-in DataHub quickstart is Apple-Silicon only; current architecture is $architecture." >&2
    exit 2
  fi
  datahub_images=(
    confluentinc/cp-kafka:7.9.2
    acryldata/datahub-actions:v1.6.0-slim
    acryldata/datahub-frontend-react:v1.6.0
    acryldata/datahub-gms:v1.6.0
    acryldata/datahub-upgrade:v1.6.0
    elasticsearch:7.10.1
    acryldata/datahub-kafka-setup:head
    mariadb:10.5.8
    confluentinc/cp-schema-registry:7.9.2
    confluentinc/cp-zookeeper:7.9.2
  )
  save_bundle "datahub-v1.6.0-mac-dev-$architecture" "${datahub_images[@]}"

  datahub_source="$root/runtime/datahub-v1.6.0"
  if [ ! -d "$datahub_source/.git" ]; then
    echo "Missing official DataHub source checkout: $datahub_source" >&2
    echo "The image bundle was created, but the local DataHub source bundle was not." >&2
    exit 2
  fi
  expected_datahub_commit=059a36c0b035a6057de00114ccac0ea9003d6bc2
  if [ "$(git -C "$datahub_source" rev-parse HEAD)" != "$expected_datahub_commit" ]; then
    echo "DataHub source checkout is not the approved v1.6.0 commit $expected_datahub_commit." >&2
    exit 2
  fi
  bundle_name=datahub-v1.6.0-source.bundle
  git -C "$datahub_source" bundle create "$output_dir/$bundle_name" HEAD
  write_checksum "$bundle_name"
  git -C "$datahub_source" bundle verify "$output_dir/$bundle_name" >/dev/null
  printf 'Created %s\n' "$output_dir/$bundle_name"
fi

if [ "$include_observability" = true ]; then
  materialize_cross_platform_images "${observability_images[@]}"
  save_bundle "datariver-observability-pilot-$target_architecture" "${observability_images[@]}"
fi

printf 'Offline image export complete for %s/%s. Verify every *.sha256 file before docker load.\n' \
  "$target_os" "$target_architecture"
