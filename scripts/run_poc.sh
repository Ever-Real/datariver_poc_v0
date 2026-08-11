#!/usr/bin/env bash
set -euo pipefail

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

action="${1:-start}"
case "${action}" in
  start|stop|status)
    shift || true
    ;;
  *)
    action="start"
    ;;
esac

archive_input="${1:-release-poc.tar.gz}"
archive_dir="$(cd -- "$(dirname -- "${archive_input}")" && pwd -P)"
archive_path="${archive_dir}/$(basename -- "${archive_input}")"
checksum_path="${archive_path}.sha256"
runtime_dir="${POC_RUNTIME_DIR:-${archive_dir}/runtime-static-poc}"
image_ref="datariver-static-poc:06111-amd64"
project_name="datariver-static-poc"

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"
[[ -f "${archive_path}" ]] || fail "release archive not found: ${archive_path}"
[[ -f "${checksum_path}" ]] || fail "checksum file not found: ${checksum_path}"
[[ -n "${runtime_dir}" && "${runtime_dir}" != "/" ]] || fail "unsafe runtime directory"

expected_sha256="$(awk 'NR == 1 {print $1}' "${checksum_path}")"
actual_sha256="$(sha256_file "${archive_path}")"
[[ "${expected_sha256}" =~ ^[0-9a-fA-F]{64}$ ]] || fail "invalid checksum file"
[[ "${actual_sha256}" == "${expected_sha256}" ]] || fail "archive checksum mismatch"
printf 'Archive checksum PASS: %s\n' "${actual_sha256}"

expected_members="$(printf '%s\n' POC_IDENTITY.json POC_LIMITATIONS.md docker-compose.poc.yaml images.tar run_poc.sh | sort)"
actual_members="$(tar -tzf "${archive_path}" | sort)"
[[ "${actual_members}" == "${expected_members}" ]] || fail "archive file inventory is not the fixed POC contract"

if [[ -d "${runtime_dir}" ]]; then
  [[ -f "${runtime_dir}/.release-poc.sha256" ]] || fail "existing runtime directory has no release marker"
  [[ "$(<"${runtime_dir}/.release-poc.sha256")" == "${actual_sha256}" ]] || fail "runtime directory belongs to a different archive"
else
  runtime_parent="$(dirname -- "${runtime_dir}")"
  mkdir -p -- "${runtime_parent}"
  stage_dir="$(mktemp -d "${runtime_parent}/.runtime-static-poc.XXXXXX")"
  cleanup_stage() {
    if [[ -n "${stage_dir:-}" && -d "${stage_dir}" ]]; then
      rm -rf -- "${stage_dir}"
    fi
  }
  trap cleanup_stage EXIT
  tar -xzf "${archive_path}" -C "${stage_dir}"
  printf '%s\n' "${actual_sha256}" > "${stage_dir}/.release-poc.sha256"
  mv -- "${stage_dir}" "${runtime_dir}"
  stage_dir=""
  trap - EXIT
fi

compose_file="${runtime_dir}/docker-compose.poc.yaml"
identity_file="${runtime_dir}/POC_IDENTITY.json"
images_file="${runtime_dir}/images.tar"
[[ -f "${compose_file}" && -f "${identity_file}" && -f "${images_file}" ]] || fail "runtime bundle is incomplete"

if grep -Eq '^[[:space:]]*(build|secrets|volumes|privileged|network_mode)[[:space:]]*:' "${compose_file}"; then
  fail "Compose contains a forbidden build, secret, volume, privileged or network-mode key"
fi
if grep -Eq 'docker\.sock|host_network|network_mode:[[:space:]]*host' "${compose_file}"; then
  fail "Compose contains a forbidden host integration"
fi

compose=(docker compose --project-name "${project_name}" --file "${compose_file}")
services="$("${compose[@]}" config --services)"
images="$("${compose[@]}" config --images)"
[[ "${services}" == "web" ]] || fail "Compose must render exactly one web service"
[[ "${images}" == "${image_ref}" ]] || fail "Compose image identity mismatch"
"${compose[@]}" config --quiet
printf 'Compose contract PASS: one image service, no build/secrets/volumes\n'

case "${action}" in
  stop)
    "${compose[@]}" down --remove-orphans
    printf 'Removed only the %s container and default network; no named volume exists.\n' "${project_name}"
    exit 0
    ;;
  status)
    "${compose[@]}" ps
    exit 0
    ;;
esac

poc_port="${POC_PORT:-39080}"
[[ "${poc_port}" =~ ^[0-9]+$ ]] || fail "POC_PORT must be numeric"
(( poc_port >= 1024 && poc_port <= 65535 )) || fail "POC_PORT must be between 1024 and 65535"

docker image load --input "${images_file}" >/dev/null
loaded_platform="$(docker image inspect "${image_ref}" --format '{{.Os}}/{{.Architecture}}')"
loaded_image_id="$(docker image inspect "${image_ref}" --format '{{.Id}}')"
expected_image_id="$(sed -n 's/^[[:space:]]*"image_id":[[:space:]]*"\([^"]*\)".*/\1/p' "${identity_file}")"
[[ "${loaded_platform}" == "linux/amd64" ]] || fail "loaded image platform is ${loaded_platform}, expected linux/amd64"
[[ -n "${expected_image_id}" && "${loaded_image_id}" == "${expected_image_id}" ]] || fail "loaded image ID does not match POC_IDENTITY.json"
printf 'Image identity PASS: %s (%s)\n' "${loaded_image_id}" "${loaded_platform}"

POC_PORT="${poc_port}" "${compose[@]}" up -d --no-build --pull never
container_id="$(POC_PORT="${poc_port}" "${compose[@]}" ps -q web)"
[[ -n "${container_id}" ]] || fail "POC web container did not start"

health=""
for _attempt in $(seq 1 30); do
  health="$(docker inspect "${container_id}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')"
  if [[ "${health}" == "healthy" || "${health}" == "running" ]]; then
    break
  fi
  if [[ "${health}" == "unhealthy" || "${health}" == "exited" || "${health}" == "dead" ]]; then
    break
  fi
  sleep 1
done

if [[ "${health}" != "healthy" && "${health}" != "running" ]]; then
  "${compose[@]}" logs --no-color web >&2 || true
  fail "POC web container health is ${health:-unknown}"
fi

printf 'POC is %s. Open http://<operations-pc-ip>:%s\n' "${health}" "${poc_port}"
printf 'Stop with: POC_RUNTIME_DIR=%q %q stop %q\n' "${runtime_dir}" "$0" "${archive_path}"
