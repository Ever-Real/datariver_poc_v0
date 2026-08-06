#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
commit=""
output_dir=""
external_images_accepted=false

# Pinned external (third-party) images used in the Pilot stack.
# Each entry is name:tag@sha256:digest  (linux/amd64).
redis_source="redis:8.2.6-bookworm@sha256:3055dc25265b0c19ec90a1756dad4e0faff6f79e2557a6ac3d1274e39ee906f6"
staging=""

usage() {
  cat <<'EOF'
Usage: scripts/export_release.sh --commit FULL_SHA --output DIR \
  --accept-redis-image-redistribution

Build one exact clean commit on a native Linux amd64 Docker host and write:
  DIR/release.tar.gz
  DIR/release.tar.gz.sha256
  DIR/deploy_pilot.sh

The archive contains runtime images and deployment assets only. It never contains
a standalone source checkout, Git metadata, .env, secrets, volumes or database data.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --commit)
      shift
      commit=${1:?--commit requires a full Git SHA}
      ;;
    --output)
      shift
      output_dir=${1:?--output requires a directory}
      ;;
    --accept-external-images)
      external_images_accepted=true
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

case "$commit" in
  [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
  *)
    echo "--commit must be one full 40-character hexadecimal Git SHA." >&2
    exit 2
    ;;
esac
commit=$(printf '%s' "$commit" | tr '[:upper:]' '[:lower:]')

if [ -z "$output_dir" ]; then
  output_dir="$root/docker_imgs/datariver-$(printf '%s' "$commit" | cut -c1-12)"
fi
if [ "$external_images_accepted" != true ]; then
  echo "Exporting pinned external images (Redis, pgvector, Keycloak, Node) requires" >&2
  echo "  --accept-external-images" >&2
  echo "Verify the license/redistribution terms for each pinned image before running." >&2
  exit 2
fi
for command in docker find git install sha256sum sort tar xargs; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command is unavailable: $command" >&2
    exit 2
  fi
done

resolved_commit=$(git -C "$root" rev-parse --verify "$commit^{commit}")
if [ "$resolved_commit" != "$commit" ]; then
  echo "The requested SHA does not resolve to that exact commit." >&2
  exit 2
fi
head_commit=$(git -C "$root" rev-parse --verify HEAD)
if [ "$head_commit" != "$commit" ]; then
  echo "Checkout mismatch: HEAD is $head_commit, requested commit is $commit." >&2
  echo "Select the reviewed commit before exporting; this script never changes the checkout." >&2
  exit 2
fi
if [ -n "$(git -C "$root" status --porcelain --untracked-files=normal)" ]; then
  echo "Release export requires a clean worktree at the requested commit." >&2
  exit 2
fi

docker_os=$(docker version --format '{{.Server.Os}}')
docker_arch=$(docker version --format '{{.Server.Arch}}')
case "$docker_arch" in
  amd64|x86_64) docker_arch=amd64 ;;
esac
if [ "$docker_os/$docker_arch" != "linux/amd64" ]; then
  echo "Pilot export requires a native linux/amd64 Docker daemon; found $docker_os/$docker_arch." >&2
  exit 2
fi

release_id="datariver-$(printf '%s' "$commit" | cut -c1-12)"
archive="$output_dir/release.tar.gz"
archive_checksum="$archive.sha256"
if [ -e "$archive" ] || [ -e "$archive_checksum" ]; then
  echo "Release output is immutable and already exists: $output_dir" >&2
  exit 2
fi
mkdir -p "$output_dir"
staging=$(mktemp -d "$output_dir/.${release_id}.partial.XXXXXX")

cleanup() {
  status=$?
  if [ -n "$staging" ] && [ -d "$staging" ]; then
    rm -rf -- "$staging"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

release_root="$staging/$release_id"
mkdir -p "$release_root/secrets.example"

backend_image="datariver-pilot-backend:$release_id"
web_image="datariver-pilot-web:$release_id"
keycloak_image="datariver-pilot-keycloak:$release_id"
postgres_image="datariver-pilot-postgres:$release_id"
redis_image="datariver-pilot-redis:$release_id"

for df in backend/Dockerfile frontend/Dockerfile infra/keycloak/Dockerfile infra/pilot/postgres/Dockerfile; do
  grep -E '^FROM ' "$root/$df" | awk '{print $2}' | while read -r base; do
    if echo "$base" | grep -q '@sha256:'; then
      base_no_digest=$(echo "$base" | sed 's/@sha256:[^ ]*//g')
      docker image tag "$base" "$base_no_digest" >/dev/null 2>&1 || true
    fi
  done
done

build_image() {
  local dockerfile=$1
  local image=$2
  
  local tmp_df="$staging/$(basename "$dockerfile")"
  sed 's/@sha256:[^ ]*//g' "$root/$dockerfile" > "$tmp_df"

  docker build \
    --platform linux/amd64 \
    --label "org.opencontainers.image.revision=$commit" \
    --file "$tmp_df" \
    --tag "$image" \
    "$root"
}

build_image backend/Dockerfile "$backend_image"
build_image frontend/Dockerfile "$web_image"
build_image infra/keycloak/Dockerfile "$keycloak_image"
build_image infra/pilot/postgres/Dockerfile "$postgres_image"

# Pull/verify all pinned third-party images.
pull_or_verify() {
  local ref=$1 label=$2
  local no_digest; no_digest=$(echo "$ref" | sed 's/@sha256:[^ ]*//g')
  if ! docker image inspect "$ref" >/dev/null 2>&1; then
    if docker image inspect "$no_digest" >/dev/null 2>&1; then
      ref="$no_digest"
    else
      echo "Pulling $label..."
      docker image pull --platform linux/amd64 "$ref"
    fi
  fi
  local platform; platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$ref")
  if [ "$platform" != linux/amd64 ]; then
    echo "$label image is $platform, expected linux/amd64." >&2
    exit 2
  fi
  echo "$ref"
}

redis_source=$(pull_or_verify "$redis_source" Redis)
docker image tag "$redis_source" "$redis_image"

images=(
  "$backend_image"
  "$web_image"
  "$keycloak_image"
  "$postgres_image"
  "$redis_image"
)

{
  printf 'image\timage_id\tplatform\tsource_commit\tbuild_input\n'
  for image in "${images[@]}"; do
    platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
    if [ "$platform" != linux/amd64 ]; then
      echo "Image $image is $platform, expected linux/amd64." >&2
      exit 2
    fi
    image_id=$(docker image inspect --format '{{.Id}}' "$image")
    case "$image" in
      "$backend_image") build_input=backend/Dockerfile ;;
      "$web_image") build_input=frontend/Dockerfile ;;
      "$keycloak_image") build_input=infra/keycloak/Dockerfile ;;
      "$postgres_image") build_input=infra/pilot/postgres/Dockerfile ;;
      "$redis_image") build_input=$redis_source ;;
      *) echo "Unknown release image: $image" >&2; exit 2 ;;
    esac
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$image" "$image_id" "$platform" "$commit" "$build_input"
  done
} >"$release_root/image-manifest.tsv"

docker image save --output "$release_root/images.tar" "${images[@]}"
printf '%s\n' "$release_id" >"$release_root/release-id.txt"
printf '%s\n' "$commit" >"$release_root/source-commit.txt"
install -m 0644 "$root/deploy/pilot/docker-compose.yaml" "$release_root/docker-compose.yaml"
install -m 0644 "$root/deploy/pilot/.env.example" "$release_root/.env.example"
install -m 0644 \
  "$root/deploy/pilot/secrets.example/README.md" \
  "$root/deploy/pilot/secrets.example/generated-files.txt" \
  "$root/deploy/pilot/secrets.example/operator-files.txt" \
  "$release_root/secrets.example/"
install -m 0644 \
  "$root/infra/keycloak/datariver-realm.template.json" \
  "$release_root/keycloak-realm.template.json"
install -m 0755 "$root/scripts/deploy_pilot.sh" "$release_root/deploy_pilot.sh"

(
  cd "$release_root"
  find . -type f ! -name SHA256SUMS -print0 |
    sort -z |
    xargs -0 sha256sum >SHA256SUMS
)

tar -C "$staging" -czf "$archive" "$release_id"
(
  cd "$output_dir"
  sha256sum release.tar.gz >release.tar.gz.sha256
)
install -m 0755 "$root/scripts/deploy_pilot.sh" "$output_dir/deploy_pilot.sh"

printf 'Created source-free Pilot release for %s\n' "$commit"
printf '  archive: %s\n' "$archive"
printf '  checksum: %s\n' "$archive_checksum"
printf '  deployer: %s\n' "$output_dir/deploy_pilot.sh"
printf 'Transfer only those three files through the approved path.\n'

rm -rf -- "$staging"
staging=""
trap - EXIT HUP INT TERM
