#!/usr/bin/env bash
set -euo pipefail

release_root=
requested_platform=
load_images=false
artifact_only=false
source_dir=
env_file=

usage() {
  cat <<'EOF'
Usage: scripts/verify_offline_release.sh RELEASE_DIR --platform linux/ARCH [options]

Verify an immutable DataRiver source/image release before migration.

Options:
  --load                  Load image tar files, then verify every image ID and platform.
  --artifact-only         Verify source/checksums/manifests without requiring a matching daemon.
                          Use this on a cross-build host; never use it as target import evidence.
  --source-dir DIR        Require this checkout to match the release commit and contracts.
  --env-file FILE         With --source-dir and --load, render core+identity Compose and prove
                          that every selected image is already local (no pull/build is run).
EOF
}

if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
  release_root=$1
  shift
fi
while [ "$#" -gt 0 ]; do
  case "$1" in
    --platform)
      shift
      requested_platform=${1:?--platform requires a value}
      ;;
    --load)
      load_images=true
      ;;
    --artifact-only)
      artifact_only=true
      ;;
    --source-dir)
      shift
      source_dir=${1:?--source-dir requires a directory}
      ;;
    --env-file)
      shift
      env_file=${1:?--env-file requires a file}
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

[ -n "$release_root" ] || { usage >&2; exit 2; }
[ -d "$release_root" ] || { echo "Release directory does not exist: $release_root" >&2; exit 2; }
[ -n "$requested_platform" ] || { echo "--platform is required." >&2; exit 2; }
release_root=$(CDPATH= cd -- "$release_root" && pwd)

normalize_architecture() {
  case "$1" in
    arm64|aarch64) printf 'arm64' ;;
    amd64|x86_64) printf 'amd64' ;;
    *) return 1 ;;
  esac
}

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

case "$requested_platform" in
  linux/arm64|linux/aarch64|linux/amd64|linux/x86_64)
    requested_architecture=$(normalize_architecture "${requested_platform#*/}")
    ;;
  *)
    echo "Unsupported platform: $requested_platform" >&2
    exit 2
    ;;
esac
normalized_platform="linux/$requested_architecture"
[ "$artifact_only" != true ] || [ "$load_images" != true ] || {
  echo "--artifact-only and --load are mutually exclusive." >&2
  exit 2
}
[ "$artifact_only" != true ] || [ -z "$env_file" ] || {
  echo "--artifact-only cannot perform target Compose image verification." >&2
  exit 2
}
platform_dir="$release_root/$requested_architecture"
index="$platform_dir/release-index.tsv"
marker="$release_root/source-commit.txt"
bundle="$release_root/datariver-source.bundle"

for required in \
  "$index" "$index.sha256" "$marker" "$marker.sha256" \
  "$bundle" "$bundle.sha256" "$platform_dir/offline-core.compose.yaml" \
  "$platform_dir/offline-core.compose.yaml.sha256"; do
  [ -f "$required" ] || { echo "Release artifact is missing: $required" >&2; exit 2; }
done

verify_checksums() {
  local directory=$1
  local checksum
  for checksum in "$directory"/*.sha256; do
    [ -f "$checksum" ] || continue
    if ! (
      cd "$directory"
      if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -c "$(basename "$checksum")"
      else
        shasum -a 256 -c "$(basename "$checksum")"
      fi
    ); then
      echo "Checksum verification failed: $checksum" >&2
      return 2
    fi
  done
}

verify_checksums "$release_root"
verify_checksums "$platform_dir"

release_flag() {
  local name=$1 value
  value=$(awk -F '\t' -v name="$name" \
    '$1 == "release" && $2 == name { print $3 }' "$index")
  case "$value" in
    true|false) printf '%s' "$value" ;;
    *) echo "Release index has an invalid or missing $name flag." >&2; return 2 ;;
  esac
}

include_airflow=$(release_flag include_airflow)
include_edge=$(release_flag include_edge)
include_graph=$(release_flag include_graph)
include_local_connectors=$(release_flag include_local_connectors)
include_datahub_mac_dev=$(release_flag include_datahub_mac_dev)
include_observability=$(release_flag include_observability)

require_platform_artifact() {
  local artifact=$1
  [ -s "$platform_dir/$artifact" ] || {
    echo "Selected release artifact is missing: $platform_dir/$artifact" >&2
    return 2
  }
  [ -f "$platform_dir/$artifact.sha256" ] || {
    echo "Selected release artifact checksum is missing: $platform_dir/$artifact.sha256" >&2
    return 2
  }
}

if [ "$include_airflow" = true ] || [ "$include_edge" = true ] || [ "$include_graph" = true ]; then
  require_platform_artifact "datariver-optional-$requested_architecture.tar"
  require_platform_artifact "datariver-optional-$requested_architecture.manifest.tsv"
fi
if [ "$include_airflow" = true ]; then
  require_platform_artifact offline-airflow.compose.yaml
fi
if [ "$include_graph" = true ]; then
  require_platform_artifact offline-graph.compose.yaml
fi
if [ "$include_local_connectors" = true ]; then
  require_platform_artifact "datariver-local-connectors-$requested_architecture.tar"
  require_platform_artifact "datariver-local-connectors-$requested_architecture.manifest.tsv"
  require_platform_artifact offline-local-connectors.compose.yaml
fi
if [ "$include_observability" = true ]; then
  require_platform_artifact "datariver-observability-pilot-$requested_architecture.tar"
  require_platform_artifact "datariver-observability-pilot-$requested_architecture.manifest.tsv"
fi
if [ "$include_datahub_mac_dev" = true ]; then
  require_platform_artifact "datahub-v1.6.0-mac-dev-$requested_architecture.tar"
  require_platform_artifact "datahub-v1.6.0-mac-dev-$requested_architecture.manifest.tsv"
  require_platform_artifact datahub-v1.6.0-source.bundle
fi
verification_repository=$(mktemp -d "${TMPDIR:-/tmp}/datariver-release-verify.XXXXXX")
manifest_inventory=
cleanup_verification() {
  rm -rf "$verification_repository"
  if [ -n "$manifest_inventory" ]; then
    rm -f "$manifest_inventory"
  fi
}
trap cleanup_verification EXIT HUP INT TERM
git init --bare --quiet "$verification_repository"
git -C "$verification_repository" bundle verify "$bundle" >/dev/null

source_commit=$(tr -d '\r\n' <"$marker")
release_id=$(awk -F '\t' '$1 == "release" && $2 == "release_id" { print $3 }' "$index")
index_commit=$(awk -F '\t' '$1 == "release" && $2 == "source_commit" { print $3 }' "$index")
index_platform=$(awk -F '\t' '$1 == "release" && $2 == "platform" { print $3 }' "$index")
[ "$release_id" = "$(basename "$release_root")" ] || { echo "Release ID/directory mismatch." >&2; exit 2; }
[ "$source_commit" = "$index_commit" ] || { echo "Source commit/index mismatch." >&2; exit 2; }
[ "$normalized_platform" = "$index_platform" ] || {
  echo "Release is $index_platform, requested $normalized_platform." >&2
  exit 2
}
source_hash=$(awk -F '\t' '$1 == "source" && $2 == "bundle" { print $4 }' "$index")
[ -n "$source_hash" ] && [ "$(file_sha256 "$bundle")" = "$source_hash" ] || {
  echo "Source bundle/release index mismatch." >&2
  exit 2
}

core_archive="datariver-core-$requested_architecture.tar"
core_manifest="datariver-core-$requested_architecture.manifest.tsv"
for required_core in "$platform_dir/$core_archive" "$platform_dir/$core_manifest"; do
  [ -s "$required_core" ] || { echo "Core release artifact is missing: $required_core" >&2; exit 2; }
done
for artifact in \
  "$platform_dir"/*.tar "$platform_dir"/*.manifest.tsv "$platform_dir"/*.compose.yaml \
  "$platform_dir"/*.bundle; do
  [ -f "$artifact" ] || continue
  artifact_name=$(basename "$artifact")
  indexed_hash=$(awk -F '\t' -v name="$artifact_name" \
    '$1 == "artifact" && $2 == name { print $3 }' "$index")
  [ -n "$indexed_hash" ] || { echo "Artifact is absent from release index: $artifact_name" >&2; exit 2; }
  [ "$(file_sha256 "$artifact")" = "$indexed_hash" ] || {
    echo "Artifact/release index mismatch: $artifact_name" >&2
    exit 2
  }
done
while IFS="$(printf '\t')" read -r record artifact_name indexed_hash _extra; do
  [ "$record" = artifact ] || continue
  case "$artifact_name" in
    ''|*/*|*\\*) echo "Invalid indexed artifact name: $artifact_name" >&2; exit 2 ;;
  esac
  [ -f "$platform_dir/$artifact_name" ] || {
    echo "Indexed artifact is missing: $artifact_name" >&2
    exit 2
  }
  [ -f "$platform_dir/$artifact_name.sha256" ] || {
    echo "Indexed artifact checksum is missing: $artifact_name" >&2
    exit 2
  }
  [ "$(file_sha256 "$platform_dir/$artifact_name")" = "$indexed_hash" ] || {
    echo "Indexed artifact hash mismatch: $artifact_name" >&2
    exit 2
  }
done <"$index"
for manifest in "$platform_dir"/*.manifest.tsv; do
  [ -f "$manifest" ] || continue
  awk -F '\t' -v platform="$normalized_platform" '
    NR == 1 {
      if ($0 != "image\timage_id\trepository_digests\tplatform") exit 2
      next
    }
    NF != 4 || $1 == "" || $2 !~ /^sha256:[0-9a-f]{64}$/ || $4 != platform { exit 2 }
    { count += 1 }
    END { if (count == 0) exit 2 }
  ' "$manifest" || { echo "Invalid image manifest: $manifest" >&2; exit 2; }
done

if [ -n "$source_dir" ]; then
  source_dir=$(CDPATH= cd -- "$source_dir" && pwd)
  git -C "$source_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "Source directory is not a Git checkout: $source_dir" >&2
    exit 2
  }
  [ "$(git -C "$source_dir" rev-parse --verify HEAD)" = "$source_commit" ] || {
    echo "Source checkout does not match release commit $source_commit." >&2
    exit 2
  }
  [ -z "$(git -C "$source_dir" status --porcelain --untracked-files=normal)" ] || {
    echo "Source checkout is not clean." >&2
    exit 2
  }
  while IFS="$(printf '\t')" read -r record path expected_hash _extra; do
    [ "$record" = contract ] || continue
    [ -f "$source_dir/$path" ] || { echo "Release contract file is missing: $path" >&2; exit 2; }
    actual_hash=$(git -C "$source_dir" hash-object "$source_dir/$path")
    [ "$actual_hash" = "$expected_hash" ] || { echo "Release contract changed: $path" >&2; exit 2; }
  done <"$index"
fi

if [ "$artifact_only" = true ]; then
  printf 'Verified DataRiver release artifacts %s for %s at source commit %s.\n' \
    "$release_id" "$normalized_platform" "$source_commit"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for target platform and image verification." >&2
  exit 2
fi
daemon_os=$(docker version --format '{{.Server.Os}}')
daemon_architecture=$(normalize_architecture "$(docker version --format '{{.Server.Arch}}')") || {
  echo "Target Docker daemon has an unsupported architecture." >&2
  exit 2
}
[ "$daemon_os/$daemon_architecture" = "$normalized_platform" ] || {
  echo "Target Docker daemon is $daemon_os/$daemon_architecture, release is $normalized_platform." >&2
  exit 2
}

if [ "$load_images" = true ]; then
  for archive in "$platform_dir"/*.tar; do
    [ -f "$archive" ] || continue
    docker image load --input "$archive" >/dev/null
  done

  for manifest in "$platform_dir"/*.manifest.tsv; do
    [ -f "$manifest" ] || continue
    tail -n +2 "$manifest" | while IFS="$(printf '\t')" read -r image expected_id _digests expected_platform; do
      [ -n "$image" ] || continue
      inspect_image=${image%@sha256:*}
      actual_id=$(docker image inspect --format '{{.Id}}' "$inspect_image")
      actual_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$inspect_image")
      [ "$actual_id" = "$expected_id" ] || { echo "Loaded image ID mismatch: $image" >&2; exit 2; }
      [ "$actual_platform" = "$expected_platform" ] || { echo "Loaded image platform mismatch: $image" >&2; exit 2; }
      [ "$actual_platform" = "$normalized_platform" ] || { echo "Wrong target image platform: $image" >&2; exit 2; }
    done
  done
fi

if [ -n "$env_file" ]; then
  [ "$load_images" = true ] || { echo "--env-file requires --load for local image verification." >&2; exit 2; }
  [ -n "$source_dir" ] || { echo "--env-file requires --source-dir." >&2; exit 2; }
  [ -f "$env_file" ] || { echo "Deployment environment file is missing: $env_file" >&2; exit 2; }
  normalize_image_reference() {
    local reference=${1%@sha256:*} final_component
    final_component=${reference##*/}
    case "$final_component" in
      *:*) ;;
      *) reference="$reference:latest" ;;
    esac
    printf '%s' "$reference"
  }
  manifest_inventory=$(mktemp "${TMPDIR:-/tmp}/datariver-release-images.XXXXXX")
  for manifest in "$platform_dir"/*.manifest.tsv; do
    [ -f "$manifest" ] || continue
    tail -n +2 "$manifest" | while IFS="$(printf '\t')" read -r image expected_id _rest; do
      [ -n "$image" ] || continue
      printf '%s\t%s\n' "$(normalize_image_reference "$image")" "$expected_id"
    done >>"$manifest_inventory"
  done
  verify_compose_inventory() {
    local rendered_images image normalized_image actual_id
    rendered_images=$("$source_dir/scripts/compose.sh" --env-file "$env_file" "$@" config --images)
    while IFS= read -r image; do
      [ -n "$image" ] || continue
      normalized_image=$(normalize_image_reference "$image")
      actual_id=$(docker image inspect --format '{{.Id}}' "$normalized_image")
      awk -F '\t' -v image="$normalized_image" -v image_id="$actual_id" '
        $1 == image && $2 == image_id { found = 1 }
        END { if (!found) exit 2 }
      ' "$manifest_inventory" || {
        echo "Compose image is absent from the selected release manifests: $normalized_image" >&2
        return 2
      }
    done <<<"$rendered_images"
  }

  verify_compose_inventory \
    -f "$source_dir/compose.yaml" -f "$source_dir/compose.identity.yaml" \
    -f "$platform_dir/offline-core.compose.yaml"
  if [ "$include_airflow" = true ]; then
    verify_compose_inventory \
      -f "$source_dir/compose.yaml" -f "$source_dir/compose.identity.yaml" \
      -f "$source_dir/compose.airflow.yaml" \
      -f "$platform_dir/offline-core.compose.yaml" \
      -f "$platform_dir/offline-airflow.compose.yaml"
  fi
  if [ "$include_edge" = true ]; then
    verify_compose_inventory \
      -f "$source_dir/compose.yaml" -f "$source_dir/compose.identity.yaml" \
      -f "$source_dir/compose.gateway.yaml" \
      -f "$platform_dir/offline-core.compose.yaml"
  fi
  if [ "$include_graph" = true ]; then
    verify_compose_inventory \
      -f "$source_dir/compose.yaml" -f "$source_dir/compose.identity.yaml" \
      -f "$source_dir/compose.graph.yaml" \
      -f "$platform_dir/offline-core.compose.yaml" \
      -f "$platform_dir/offline-graph.compose.yaml"
  fi
  if [ "$include_local_connectors" = true ]; then
    verify_compose_inventory --profile object-storage \
      -f "$source_dir/compose.local-connectors.yaml" \
      -f "$platform_dir/offline-local-connectors.compose.yaml"
  fi
  if [ "$include_observability" = true ]; then
    verify_compose_inventory --profile observability \
      -f "$source_dir/compose.yaml" -f "$source_dir/aux-compose.yml" \
      -f "$platform_dir/offline-core.compose.yaml"
  fi
fi

printf 'Verified DataRiver release %s for %s at source commit %s.\n' \
  "$release_id" "$normalized_platform" "$source_commit"
