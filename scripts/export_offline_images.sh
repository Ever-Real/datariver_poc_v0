#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$root/docker_imgs"
include_datahub_mac_dev=false
include_observability=false
include_airflow=false
include_edge=false
include_graph=false
include_local_connectors=false
local_connector_license_reviewed=false
build_datariver=false
target_platform=""
release_id=""
backup_file=""
cross_platform=false
platform_staging_dir=""
source_bundle_staging=""

usage() {
  cat <<'EOF'
Usage: scripts/export_offline_images.sh [options]

Export Docker images already present on this host into architecture-specific tar bundles.
The output directory is ignored by Git and contains no source configuration or secrets.

Options:
  --output DIR                 Output directory (default: <repo>/docker_imgs).
  --platform linux/ARCH        Export arm64/aarch64 (default) or amd64/x86_64 images.
                               A non-native target is built/pulled through Buildx-compatible
                               Docker Desktop and restores every pre-existing local tag.
  --build-datariver            Build all checked-in DataRiver images before export.
  --release-id ID              Immutable release directory name (default: datariver-<git-sha>).
  --include-airflow            Add the optional Airflow image bundle.
  --include-edge               Add the optional APISIX image bundle.
  --include-graph              Add the optional Neo4j image bundle.
  --include-local-connectors   Add Redis and MinIO reference images. Requires the explicit
                               --accept-local-connector-license-review operator gate.
  --accept-local-connector-license-review
                               Confirm that the exact Redis/MinIO distributions may be copied.
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
    --release-id)
      shift
      release_id=${1:?--release-id requires a value}
      ;;
    --include-airflow)
      include_airflow=true
      ;;
    --include-edge)
      include_edge=true
      ;;
    --include-graph)
      include_graph=true
      ;;
    --include-local-connectors)
      include_local_connectors=true
      ;;
    --accept-local-connector-license-review)
      local_connector_license_reviewed=true
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

source_commit=$(git -C "$root" rev-parse --verify HEAD)
if [ -n "$(git -C "$root" status --porcelain --untracked-files=normal)" ]; then
  echo "Offline release export requires a clean Git worktree." >&2
  echo "Commit or remove every tracked/untracked source change before building artifacts." >&2
  exit 2
fi
if [ -z "$release_id" ]; then
  release_id="datariver-$(printf '%s' "$source_commit" | cut -c1-12)"
fi
case "$release_id" in
  ''|*[!A-Za-z0-9._-]*)
    echo "Release ID must contain only letters, digits, dot, underscore and hyphen." >&2
    exit 2
    ;;
esac
if [ "$include_local_connectors" = true ] && [ "$local_connector_license_reviewed" != true ]; then
  echo "Local Redis/MinIO export requires --accept-local-connector-license-review." >&2
  exit 2
fi

normalize_architecture() {
  case "$1" in
    arm64|aarch64) printf 'arm64' ;;
    amd64|x86_64) printf 'amd64' ;;
    *) return 1 ;;
  esac
}

reported_architecture=$(docker version --format '{{.Server.Arch}}')
architecture=$(normalize_architecture "$reported_architecture") || {
  echo "Unsupported Docker architecture: $reported_architecture" >&2
  exit 2
}
os=$(docker version --format '{{.Server.Os}}')
if [ "$os" != linux ]; then
  echo "Only Linux OCI images can be exported; Docker daemon reports $os/$architecture." >&2
  exit 2
fi

target_os=$os
target_architecture=$architecture
if [ -n "$target_platform" ]; then
  case "$target_platform" in
    linux/arm64|linux/aarch64|linux/amd64|linux/x86_64)
      target_os=${target_platform%/*}
      requested_architecture=${target_platform#*/}
      target_architecture=$(normalize_architecture "$requested_architecture")
      ;;
    *)
      echo "Unsupported --platform $target_platform; use linux/arm64 or linux/amd64." >&2
      exit 2
      ;;
  esac
fi
target_platform="$target_os/$target_architecture"

release_root="$output_dir/$release_id"
platform_output_dir="$release_root/$target_architecture"
if [ -e "$platform_output_dir" ]; then
  echo "Release platform directory already exists and is immutable: $platform_output_dir" >&2
  exit 2
fi
mkdir -p "$release_root"
platform_staging_dir=$(mktemp -d "$release_root/.${target_architecture}.partial.XXXXXX")
output_dir=$platform_staging_dir

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

core_images=(
  pgvector/pgvector:0.8.2-pg17-bookworm@sha256:feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966
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
  datariver-next-knowledge-source-worker:latest
  datariver-next-web:latest
  datariver-keycloak:26.7.0
)

external_platform_images=(
  pgvector/pgvector:0.8.2-pg17-bookworm@sha256:feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966
)

optional_images=()
if [ "$include_airflow" = true ]; then
  optional_images+=(datariver-airflow:3.3.0-python3.12)
fi
if [ "$include_edge" = true ]; then
  optional_images+=(datariver-apisix:3.17.0-debian)
fi
if [ "$include_graph" = true ]; then
  optional_images+=(neo4j:2026.06.0@sha256:ba2b859bdbe7017a9baa1a7b5681ac9732198753719b0a502e3645feddfdec72)
  external_platform_images+=(neo4j:2026.06.0@sha256:ba2b859bdbe7017a9baa1a7b5681ac9732198753719b0a502e3645feddfdec72)
fi

local_connector_images=(
  redis:8.2.6-bookworm@sha256:3055dc25265b0c19ec90a1756dad4e0faff6f79e2557a6ac3d1274e39ee906f6
  quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
)
if [ "$include_local_connectors" = true ]; then
  external_platform_images+=("${local_connector_images[@]}")
fi

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
  local original=$image
  case "$image" in
    *@sha256:*) original=${image%@sha256:*} ;;
  esac
  if ! docker image inspect "$original" >/dev/null 2>&1; then
    return
  fi
  local safe_image backup
  safe_image=$(printf '%s' "$original" | tr '/:@' '___')
  backup="datariver-offline-export-backup:${safe_image}-${target_architecture}-$$"
  docker image tag "$original" "$backup"
  printf '%s\t%s\n' "$original" "$backup" >>"$backup_file"
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

cleanup_release_export() {
  status=$?
  if [ "$cross_platform" = true ]; then
    restore_backed_up_tags
  fi
  if [ -n "$platform_staging_dir" ] && [ -d "$platform_staging_dir" ]; then
    rm -rf "$platform_staging_dir"
  fi
  if [ -n "$source_bundle_staging" ] && [ -f "$source_bundle_staging" ]; then
    rm -f "$source_bundle_staging"
  fi
  exit "$status"
}

trap cleanup_release_export EXIT HUP INT TERM

if [ "$cross_platform" = true ]; then
  backup_file=$(mktemp "${TMPDIR:-/tmp}/datariver-offline-images.XXXXXX")
  for image in "${core_images[@]}"; do
    backup_existing_tag "$image"
  done
  if [ "${#optional_images[@]}" -gt 0 ]; then
    for image in "${optional_images[@]}"; do
      backup_existing_tag "$image"
    done
  fi
  if [ "$include_local_connectors" = true ]; then
    for image in "${local_connector_images[@]}"; do
      backup_existing_tag "$image"
    done
  fi
  if [ "$include_observability" = true ]; then
    for image in "${observability_images[@]}"; do
      backup_existing_tag "$image"
    done
  fi
fi

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
    datariver-next-catalog-export-worker:latest \
    datariver-next-knowledge-source-worker:latest; do
    docker image tag datariver-next-api:latest "$backend_image"
  done

  docker buildx build \
    --platform "$target_platform" \
    --load \
    --file "$root/frontend/Dockerfile" \
    --tag datariver-next-web:latest \
    "$root"

  docker buildx build \
    --platform "$target_platform" \
    --load \
    --file "$root/infra/keycloak/Dockerfile" \
    --tag datariver-keycloak:26.7.0 \
    "$root"
  if [ "$include_airflow" = true ]; then
    docker buildx build \
      --platform "$target_platform" \
      --load \
      --file "$root/infra/airflow/Dockerfile" \
      --tag datariver-airflow:3.3.0-python3.12 \
      "$root"
  fi
  if [ "$include_edge" = true ]; then
    docker buildx build \
      --platform "$target_platform" \
      --load \
      --tag datariver-apisix:3.17.0-debian \
      "$root/infra/apisix"
  fi
}

materialize_cross_platform_images() {
  if [ "$cross_platform" != true ]; then
    return
  fi
  local image original pinned_id tagged_id
  for image in "$@"; do
    docker image pull --platform "$target_platform" "$image"
    case "$image" in
      *@sha256:*)
        # Docker Desktop's containerd store can retain the host-platform tag even after a
        # platform-qualified digest pull. Refresh the distributable tag separately, but accept it
        # only when it resolves to the exact platform child selected from the pinned OCI index.
        original=${image%@sha256:*}
        pinned_id=$(docker image inspect --platform "$target_platform" \
          --format '{{.Id}}' "$image")
        docker image pull --platform "$target_platform" "$original"
        tagged_id=$(docker image inspect --platform "$target_platform" \
          --format '{{.Id}}' "$original")
        if [ "$tagged_id" != "$pinned_id" ]; then
          echo "Tag $original no longer matches pinned image $image for $target_platform." >&2
          exit 2
        fi
        ;;
    esac
  done
}

if [ "$build_datariver" = true ]; then
  if [ "$cross_platform" = true ]; then
    build_cross_platform_images
  else
    build_services=(
      migrate storage-init local-bootstrap semiconductor-seed api outbox-relay
      upload-worker upload-validation-worker governance-apply-worker
      catalog-export-worker knowledge-source-worker web keycloak
    )
    compose_files=(-f "$root/compose.yaml" -f "$root/compose.identity.yaml")
    if [ "$include_airflow" = true ]; then
      compose_files+=(-f "$root/compose.airflow.yaml")
      build_services+=(airflow-api-server)
    fi
    if [ "$include_edge" = true ]; then
      compose_files+=(-f "$root/compose.gateway.yaml")
      build_services+=(apisix)
    fi
    DATARIVER_ENV_FILE="${DATARIVER_ENV_FILE:-$root/.env}" docker compose \
      --env-file "${DATARIVER_ENV_FILE:-$root/.env}" \
      "${compose_files[@]}" build "${build_services[@]}"
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
  platform=$(docker image inspect --platform "$target_platform" \
    --format '{{.Os}}/{{.Architecture}}' "$image")
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

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

ensure_source_bundle() {
  local marker="$release_root/source-commit.txt"
  local bundle="$release_root/datariver-source.bundle"
  if [ -f "$marker" ]; then
    if [ "$(tr -d '\r\n' <"$marker")" != "$source_commit" ]; then
      echo "Release ID $release_id is already bound to another source commit." >&2
      exit 2
    fi
    [ -f "$bundle" ] || { echo "Release source bundle is missing: $bundle" >&2; exit 2; }
    [ -f "$release_root/datariver-source.bundle.sha256" ] || {
      echo "Release source bundle checksum is missing." >&2
      exit 2
    }
    [ -f "$release_root/source-commit.txt.sha256" ] || {
      echo "Release source marker checksum is missing." >&2
      exit 2
    }
    git -C "$root" bundle verify "$bundle" >/dev/null
    return
  fi
  mkdir -p "$release_root"
  source_bundle_staging="$bundle.partial.$$"
  git -C "$root" bundle create "$source_bundle_staging" HEAD
  git -C "$root" bundle verify "$source_bundle_staging" >/dev/null
  mv "$source_bundle_staging" "$bundle"
  source_bundle_staging=""
  printf '%s\n' "$source_commit" >"$marker"
  (
    cd "$release_root"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum datariver-source.bundle >datariver-source.bundle.sha256
    else
      shasum -a 256 datariver-source.bundle >datariver-source.bundle.sha256
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum source-commit.txt >source-commit.txt.sha256
    else
      shasum -a 256 source-commit.txt >source-commit.txt.sha256
    fi
  )
}

write_offline_compose_overrides() {
  printf '%s\n' \
    'services:' \
    '  postgres:' \
    '    image: pgvector/pgvector:0.8.2-pg17-bookworm' \
    >"$output_dir/offline-core.compose.yaml"
  write_checksum offline-core.compose.yaml

  if [ "$include_airflow" = true ]; then
    printf '%s\n' \
      'services:' \
      '  airflow-db-init:' \
      '    image: postgres:17.10-bookworm' \
      >"$output_dir/offline-airflow.compose.yaml"
    write_checksum offline-airflow.compose.yaml
  fi
  if [ "$include_graph" = true ]; then
    printf '%s\n' \
      'services:' \
      '  neo4j:' \
      '    image: neo4j:2026.06.0' \
      >"$output_dir/offline-graph.compose.yaml"
    write_checksum offline-graph.compose.yaml
  fi
  if [ "$include_local_connectors" = true ]; then
    printf '%s\n' \
      'services:' \
      '  redis-cache:' \
      '    image: redis:8.2.6-bookworm' \
      '  redis-delivery:' \
      '    image: redis:8.2.6-bookworm' \
      '  minio:' \
      '    image: quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z' \
      >"$output_dir/offline-local-connectors.compose.yaml"
    write_checksum offline-local-connectors.compose.yaml
  fi
}

write_manifest() {
  local label=$1
  shift
  local manifest="$output_dir/$label.manifest.tsv"
  {
    printf 'image\timage_id\trepository_digests\tplatform\n'
    local image repository_digests
    for image in "$@"; do
      repository_digests=$(docker image inspect --platform "$target_platform" \
        --format '{{join .RepoDigests ","}}' "$image" | awk -F ',' '
          {
            separator = ""
            for (field_index = 1; field_index <= NF; field_index += 1) {
              if ($field_index !~ /^datariver-offline-export-backup@/) {
                printf "%s%s", separator, $field_index
                separator = ","
              }
            }
            printf "\n"
          }
        ')
      printf '%s\t%s\t%s\t%s\n' \
        "$image" \
        "$(docker image inspect --platform "$target_platform" --format '{{.Id}}' "$image")" \
        "$repository_digests" \
        "$(docker image inspect --platform "$target_platform" \
          --format '{{.Os}}/{{.Architecture}}' "$image")"
    done
  } >"$manifest"
  write_checksum "$(basename "$manifest")"
}

save_bundle() {
  local label=$1
  shift
  local image save_image archive_manifest
  local save_images=()
  for image in "$@"; do
    require_image "$image"
    save_image=$image
    case "$image" in
      *@sha256:*) save_image=${image%@sha256:*} ;;
    esac
    save_images+=("$save_image")
  done
  local tar_name="$label.tar"
  local temporary="$output_dir/$tar_name.partial"
  docker image save --platform "$target_platform" --output "$temporary" "${save_images[@]}"
  archive_manifest="$output_dir/$tar_name.manifest.partial"
  tar -xOf "$temporary" manifest.json >"$archive_manifest"
  for save_image in "${save_images[@]}"; do
    if ! grep -F "\"$save_image\"" "$archive_manifest" >/dev/null; then
      echo "Saved archive omitted required image tag: $save_image" >&2
      exit 2
    fi
  done
  rm -f "$archive_manifest"
  mv "$temporary" "$output_dir/$tar_name"
  write_checksum "$tar_name"
  write_manifest "$label" "$@"
  printf 'Created %s\n' "$output_dir/$tar_name"
}

write_release_index() {
  local index="$output_dir/release-index.tsv"
  local artifact relative_path
  local contract_files=(
    pyproject.toml uv.lock frontend/package-lock.json backend/Dockerfile frontend/Dockerfile
    compose.yaml compose.identity.yaml
  )
  if [ "$include_airflow" = true ]; then
    contract_files+=(compose.airflow.yaml infra/airflow/Dockerfile infra/postgres/init-airflow.sh)
  fi
  if [ "$include_edge" = true ]; then
    contract_files+=(compose.gateway.yaml infra/apisix/Dockerfile)
  fi
  if [ "$include_graph" = true ]; then
    contract_files+=(compose.graph.yaml)
  fi
  if [ "$include_local_connectors" = true ]; then
    contract_files+=(compose.local-connectors.yaml)
  fi
  if [ "$include_observability" = true ]; then
    contract_files+=(
      aux-compose.yml
      infra/observability/alertmanager.yml
      infra/observability/loki.yaml
      infra/observability/otel-collector.yaml
      infra/observability/prometheus.yml
      infra/observability/tempo.yaml
    )
  fi
  {
    printf 'record\tname\tvalue\textra\n'
    printf 'release\trelease_id\t%s\t\n' "$release_id"
    printf 'release\tsource_commit\t%s\t\n' "$source_commit"
    printf 'release\tplatform\t%s\t\n' "$target_platform"
    printf 'release\tbuild_host_platform\t%s/%s\t\n' "$os" "$architecture"
    printf 'release\tinclude_airflow\t%s\t\n' "$include_airflow"
    printf 'release\tinclude_edge\t%s\t\n' "$include_edge"
    printf 'release\tinclude_graph\t%s\t\n' "$include_graph"
    printf 'release\tinclude_local_connectors\t%s\t\n' "$include_local_connectors"
    printf 'release\tinclude_datahub_mac_dev\t%s\t\n' "$include_datahub_mac_dev"
    printf 'release\tinclude_observability\t%s\t\n' "$include_observability"
    printf 'toolchain\tgit\t%s\t\n' "$(git --version)"
    printf 'toolchain\tdocker_client\t%s\t\n' "$(docker version --format '{{.Client.Version}}')"
    printf 'release\tdocker_server_version\t%s\t\n' "$(docker version --format '{{.Server.Version}}')"
    printf 'toolchain\tdocker_compose\t%s\t\n' \
      "$(docker compose version --short 2>/dev/null || printf 'unavailable')"
    printf 'toolchain\tdocker_buildx\t%s\t\n' \
      "$(docker buildx version 2>/dev/null || printf 'unavailable')"
    printf 'release\tcreated_at_utc\t%s\t\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'source\tbundle\t../datariver-source.bundle\t%s\n' \
      "$(file_sha256 "$release_root/datariver-source.bundle")"
    for relative_path in "${contract_files[@]}"; do
      printf 'contract\t%s\t%s\t\n' "$relative_path" \
        "$(git -C "$root" hash-object "$root/$relative_path")"
    done
    for artifact in \
      "$output_dir"/*.tar "$output_dir"/*.manifest.tsv "$output_dir"/*.compose.yaml \
      "$output_dir"/*.bundle; do
      [ -f "$artifact" ] || continue
      printf 'artifact\t%s\t%s\t\n' "$(basename "$artifact")" "$(file_sha256 "$artifact")"
    done
  } >"$index"
  write_checksum "$(basename "$index")"
}

ensure_source_bundle
write_offline_compose_overrides
materialize_cross_platform_images "${external_platform_images[@]}"
save_bundle "datariver-core-$target_architecture" "${core_images[@]}"

if [ "${#optional_images[@]}" -gt 0 ]; then
  save_bundle "datariver-optional-$target_architecture" "${optional_images[@]}"
fi

if [ "$include_local_connectors" = true ]; then
  save_bundle "datariver-local-connectors-$target_architecture" "${local_connector_images[@]}"
fi

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

write_release_index
mv "$platform_staging_dir" "$platform_output_dir"
platform_staging_dir=""

printf 'Offline release export complete: %s (%s). Verify every *.sha256 file before docker load.\n' \
  "$release_root" "$target_platform"
