#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "${script_dir}/.." && pwd -P)"
source_base="06111ae9d94bb423adbd62d31cc56fc43feafd66"
image_ref="datariver-static-poc:06111-amd64"
default_output="${repository_root}/dist/poc-release-06111-amd64"
output_dir="${1:-${default_output}}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail "sha256sum or shasum is required"
  fi
}

command -v git >/dev/null 2>&1 || fail "git is required"
command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

[[ "$(git -C "${repository_root}" rev-parse --show-toplevel)" == "${repository_root}" ]] || fail "unexpected repository root"
source_commit="$(git -C "${repository_root}" rev-parse HEAD)"
git -C "${repository_root}" merge-base --is-ancestor "${source_base}" "${source_commit}" || fail "source baseline is not an ancestor of HEAD"
[[ "$(git -C "${repository_root}" branch --show-current)" == "dev" ]] || fail "POC release must be exported from local dev"
[[ -z "$(git -C "${repository_root}" status --porcelain --untracked-files=all)" ]] || fail "POC release requires a clean committed tree"
[[ -z "$(git -C "${repository_root}" remote)" ]] || fail "isolated POC repository must have no Git remote"
[[ ! -e "${output_dir}" ]] || fail "output path already exists: ${output_dir}"

docker buildx build \
  --platform linux/amd64 \
  --pull=false \
  --load \
  --build-arg "POC_SOURCE_COMMIT=${source_commit}" \
  --file "${repository_root}/deploy/poc/Dockerfile.example" \
  --tag "${image_ref}" \
  "${repository_root}"

image_platform="$(docker image inspect "${image_ref}" --format '{{.Os}}/{{.Architecture}}')"
[[ "${image_platform}" == "linux/amd64" ]] || fail "built image platform is ${image_platform}, expected linux/amd64"
image_id="$(docker image inspect "${image_ref}" --format '{{.Id}}')"
[[ "${image_id}" == sha256:* ]] || fail "unable to record an immutable image ID"

stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/datariver-poc-export.XXXXXX")"
cleanup() {
  rm -rf -- "${stage_dir}"
}
trap cleanup EXIT

install -m 0644 "${repository_root}/deploy/poc/docker-compose.poc.yaml" "${stage_dir}/docker-compose.poc.yaml"
install -m 0644 "${repository_root}/deploy/poc/POC_LIMITATIONS.md" "${stage_dir}/POC_LIMITATIONS.md"
install -m 0755 "${repository_root}/scripts/run_poc.sh" "${stage_dir}/run_poc.sh"
docker image save --output "${stage_dir}/images.tar" "${image_ref}"

created_at_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
cat > "${stage_dir}/POC_IDENTITY.json" <<EOF
{
  "project": "datariver_poc_v0",
  "source_base": "${source_base}",
  "source_commit": "${source_commit}",
  "release_type": "STATIC_POC",
  "authentication": "NONE",
  "canonical_data": "NONE",
  "external_integrations": "SIMULATED",
  "fixture_classification": "SYNTHETIC_NON_SENSITIVE",
  "platform": "linux/amd64",
  "image": "${image_ref}",
  "image_id": "${image_id}",
  "created_at_utc": "${created_at_utc}",
  "archive_sha256": "RECORDED_BESIDE_ARCHIVE"
}
EOF

mkdir -p -- "${output_dir}"
install -m 0644 "${stage_dir}/images.tar" "${output_dir}/images.tar"
install -m 0644 "${stage_dir}/docker-compose.poc.yaml" "${output_dir}/docker-compose.poc.yaml"
install -m 0644 "${stage_dir}/POC_LIMITATIONS.md" "${output_dir}/POC_LIMITATIONS.md"
install -m 0644 "${stage_dir}/POC_IDENTITY.json" "${output_dir}/POC_IDENTITY.json"
install -m 0755 "${stage_dir}/run_poc.sh" "${output_dir}/run_poc.sh"

COPYFILE_DISABLE=1 tar -C "${stage_dir}" -czf "${output_dir}/release-poc.tar.gz" \
  images.tar docker-compose.poc.yaml run_poc.sh POC_LIMITATIONS.md POC_IDENTITY.json
archive_sha256="$(sha256_file "${output_dir}/release-poc.tar.gz")"
printf '%s  %s\n' "${archive_sha256}" "release-poc.tar.gz" > "${output_dir}/release-poc.tar.gz.sha256"

printf 'POC release exported\n'
printf '  output: %s\n' "${output_dir}"
printf '  source commit: %s\n' "${source_commit}"
printf '  image: %s\n' "${image_ref}"
printf '  image ID: %s\n' "${image_id}"
printf '  platform: %s\n' "${image_platform}"
printf '  archive SHA-256: %s\n' "${archive_sha256}"
