#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$root/offline_python"
uv_bin=${UV_BIN:-uv}
force=false

usage() {
  cat <<'EOF'
Usage: scripts/export_offline_python_cache.sh [options]

Create a portable uv cache archive for this exact frozen Python dependency set.
Run on a connected host with the same OS, CPU architecture, Python 3.12 and uv
version as the offline target. The archive is an ignored artifact; do not commit
it or include secrets, .env, source virtual environments, or application data.

Options:
  --output DIR       Artifact output directory (default: <repo>/offline_python).
  --uv-bin PATH      uv 0.9.17 executable (default: UV_BIN or uv on PATH).
  --force            Replace an archive for the same lockfile and platform.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      shift
      output_dir=${1:?--output requires a directory}
      ;;
    --uv-bin)
      shift
      uv_bin=${1:?--uv-bin requires an executable path}
      ;;
    --force)
      force=true
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

if ! command -v "$uv_bin" >/dev/null 2>&1; then
  echo "uv executable is unavailable: $uv_bin" >&2
  exit 2
fi
if ! command -v tar >/dev/null 2>&1; then
  echo "tar is required." >&2
  exit 2
fi

uv_version=$("$uv_bin" --version)
case "$uv_version" in
  'uv 0.9.17 '*) ;;
  *)
    echo "This bundle must be created with uv 0.9.17; found: $uv_version" >&2
    exit 2
    ;;
esac

python_bin=$("$uv_bin" python find 3.12)
python_version=$("$python_bin" --version)
case "$python_version" in
  'Python 3.12.'*) ;;
  *)
    echo "Python 3.12 is required; found: $python_version" >&2
    exit 2
    ;;
esac

sha256_file() {
  local file=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    shasum -a 256 "$file" | awk '{print $1}'
  fi
}

write_checksum() {
  local file=$1
  local checksum_file="$file.sha256"
  printf '%s  %s\n' "$(sha256_file "$file")" "$(basename "$file")" >"$checksum_file"
}

os=$(uname -s | tr '[:upper:]' '[:lower:]')
architecture=$(uname -m)
lock_hash=$(sha256_file "$root/uv.lock")
artifact_name="datariver-uv-cache-${os}-${architecture}-${lock_hash:0:12}"
archive="$output_dir/$artifact_name.tar.gz"
manifest="$output_dir/$artifact_name.manifest.tsv"

if [ "$force" != true ] && { [ -e "$archive" ] || [ -e "$manifest" ] || [ -e "$archive.sha256" ]; }; then
  echo "An artifact for this lockfile already exists: $archive" >&2
  echo "Use --force only after verifying that replacement is intended." >&2
  exit 2
fi

temporary_root=$(mktemp -d "${TMPDIR:-/tmp}/datariver-uv-cache.XXXXXX")
cleanup() {
  rm -rf "$temporary_root"
}
trap cleanup EXIT HUP INT TERM

cache_parent="$temporary_root/cache"
cache_dir="$cache_parent/uv"
sync_environment="$temporary_root/sync-environment"
verification_root="$temporary_root/verification"
verification_environment="$temporary_root/verification-environment"
temporary_archive="$temporary_root/$artifact_name.tar.gz"

mkdir -p "$cache_dir" "$output_dir"

UV_CACHE_DIR="$cache_dir" \
UV_PROJECT_ENVIRONMENT="$sync_environment" \
  "$uv_bin" sync --frozen --all-extras --no-editable --python "$python_bin"

tar -C "$cache_parent" -czf "$temporary_archive" uv
tar -tzf "$temporary_archive" >/dev/null

mkdir -p "$verification_root"
tar -xzf "$temporary_archive" -C "$verification_root"
UV_CACHE_DIR="$verification_root/uv" \
UV_PROJECT_ENVIRONMENT="$verification_environment" \
  "$uv_bin" sync --frozen --all-extras --no-editable --offline --python "$python_bin"

if [ "$force" = true ]; then
  rm -f "$archive" "$archive.sha256" "$manifest"
fi
mv "$temporary_archive" "$archive"
write_checksum "$archive"
{
  printf 'field\tvalue\n'
  printf 'artifact\t%s\n' "$(basename "$archive")"
  printf 'lock_sha256\t%s\n' "$lock_hash"
  printf 'platform\t%s/%s\n' "$os" "$architecture"
  printf 'uv_version\t%s\n' "$uv_version"
  printf 'python\t%s\n' "$python_version"
} >"$manifest"

printf 'Created %s\n' "$archive"
printf 'Verified offline dependency installation with %s.\n' "$uv_version"
printf 'Transfer the archive, %s and %s through an approved artifact channel.\n' \
  "$(basename "$archive.sha256")" "$(basename "$manifest")"
