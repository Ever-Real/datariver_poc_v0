#!/usr/bin/env bash
set -euo pipefail

release_root=
requested_platform=
load_images=false
source_dir=
env_file=

usage() {
  cat <<'EOF'
Usage: scripts/verify_offline_release.sh RELEASE_DIR --platform linux/ARCH [options]

Verify an immutable DataRiver source/image release before migration.

Options:
  --load                  Load image tar files, then verify every image ID and platform.
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
platform_dir="$release_root/$requested_architecture"
index="$platform_dir/release-index.tsv"
marker="$release_root/source-commit.txt"
bundle="$release_root/datariver-source.bundle"

for required in "$index" "$marker" "$bundle"; do
  [ -f "$required" ] || { echo "Release artifact is missing: $required" >&2; exit 2; }
done

verify_checksums() {
  local directory=$1
  local checksum
  for checksum in "$directory"/*.sha256; do
    [ -f "$checksum" ] || continue
    (
      cd "$directory"
      if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -c "$(basename "$checksum")"
      else
        shasum -a 256 -c "$(basename "$checksum")"
      fi
    )
  done
}

verify_checksums "$release_root"
verify_checksums "$platform_dir"
verification_repository=$(mktemp -d "${TMPDIR:-/tmp}/datariver-release-verify.XXXXXX")
trap 'rm -rf "$verification_repository"' EXIT HUP INT TERM
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
for artifact in "$platform_dir"/*.tar "$platform_dir"/*.manifest.tsv; do
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
  while IFS="$(printf '\t')" read -r record path expected_hash _extra; do
    [ "$record" = contract ] || continue
    [ -f "$source_dir/$path" ] || { echo "Release contract file is missing: $path" >&2; exit 2; }
    actual_hash=$(git -C "$source_dir" hash-object "$source_dir/$path")
    [ "$actual_hash" = "$expected_hash" ] || { echo "Release contract changed: $path" >&2; exit 2; }
  done <"$index"
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
      actual_id=$(docker image inspect --format '{{.Id}}' "$image")
      actual_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
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
  while IFS= read -r image; do
    [ -n "$image" ] || continue
    docker image inspect "$image" >/dev/null
  done < <(
    "$source_dir/scripts/compose.sh" --env-file "$env_file" \
      -f "$source_dir/compose.yaml" -f "$source_dir/compose.identity.yaml" config --images
  )
fi

printf 'Verified DataRiver release %s for %s at source commit %s.\n' \
  "$release_id" "$normalized_platform" "$source_commit"
