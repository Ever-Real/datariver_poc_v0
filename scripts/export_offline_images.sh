#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$root/docker_imgs"
include_datahub_mac_dev=false
include_observability=false
build_datariver=false

usage() {
  cat <<'EOF'
Usage: scripts/export_offline_images.sh [options]

Export Docker images already present on this host into architecture-specific tar bundles.
The output directory is ignored by Git and contains no source configuration or secrets.

Options:
  --output DIR                 Output directory (default: <repo>/docker_imgs).
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

if [ "$build_datariver" = true ]; then
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
  if [ "$platform" != "$os/$architecture" ]; then
    echo "Image $image is $platform, but the Docker daemon is $os/$architecture." >&2
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
save_bundle "datariver-platform-$architecture" "${platform_images[@]}"

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
  observability_images=(
    otel/opentelemetry-collector-contrib:0.153.0
    prom/prometheus:v3.12.0
    grafana/grafana:13.1.0
    prom/alertmanager:v0.32.1
    grafana/tempo:2.10.5
    grafana/loki:3.7.2
  )
  save_bundle "datariver-observability-pilot-$architecture" "${observability_images[@]}"
fi

printf 'Offline image export complete for %s/%s. Verify every *.sha256 file before docker load.\n' \
  "$os" "$architecture"
