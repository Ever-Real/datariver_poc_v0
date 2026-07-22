#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$root/runtime/migration/final/cutover-state"
postgres_container=datariver-next-postgres-1
redis_container=datariver-local-connectors-redis-delivery-1
include_catalog_export=false

usage() {
  cat <<'EOF'
Usage: scripts/capture_cutover_state.sh [options]

Capture and fail-closed on the final PostgreSQL/Redis cutover boundary after all writers stop.

Options:
  --output-dir DIR             Evidence directory (default: runtime/migration/final/cutover-state).
  --postgres-container NAME    PostgreSQL container name.
  --redis-container NAME       Redis delivery container name.
  --include-catalog-export     Require the optional catalog-export-v1 consumer group to be drained.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output-dir)
      shift
      output_dir=${1:?--output-dir requires a directory}
      ;;
    --postgres-container)
      shift
      postgres_container=${1:?--postgres-container requires a name}
      ;;
    --redis-container)
      shift
      redis_container=${1:?--redis-container requires a name}
      ;;
    --include-catalog-export)
      include_catalog_export=true
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

command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "jq is required." >&2; exit 2; }
case "$output_dir" in
  /*) ;;
  *) output_dir="$root/$output_dir" ;;
esac

umask 077
install -d -m 0700 "$output_dir"
docker exec -i "$postgres_container" sh -ec \
  'PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)" \
   exec psql -XqAt --set=ON_ERROR_STOP=1 -U datariver_owner -d datariver' \
  <"$root/scripts/capture_cutover_state.sql" >"$output_dir/postgres-cutover.json"
jq -e '.cutover_gate_passed == true' "$output_dir/postgres-cutover.json" >/dev/null || {
  echo "PostgreSQL cutover state is not drained; inspect $output_dir/postgres-cutover.json" >&2
  exit 2
}

docker exec "$redis_container" sh -ec \
  'exec redis-cli -a "$(cat /run/secrets/redis_delivery_password)" \
   --no-auth-warning --json XINFO GROUPS datariver:events' \
  >"$output_dir/redis-groups.json"

groups=(upload-completion-v1 upload-validation-v1 governance-apply-v1)
if [ "$include_catalog_export" = true ]; then
  groups+=(catalog-export-v1)
fi
for group in "${groups[@]}"; do
  jq -e --arg group "$group" \
    'any(.[]; .name == $group and .pending == 0 and .lag == 0)' \
    "$output_dir/redis-groups.json" >/dev/null || {
      echo "Redis consumer group $group is absent, pending, or lagging." >&2
      exit 2
    }
  docker exec "$redis_container" sh -ec \
    'exec redis-cli -a "$(cat /run/secrets/redis_delivery_password)" \
     --no-auth-warning --json XPENDING datariver:events "$1"' sh "$group" \
    >"$output_dir/redis-pending-$group.json"
done

(
  cd "$output_dir"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum postgres-cutover.json redis-groups.json redis-pending-*.json >SHA256SUMS
  else
    shasum -a 256 postgres-cutover.json redis-groups.json redis-pending-*.json >SHA256SUMS
  fi
)
chmod 0600 "$output_dir"/*.json "$output_dir/SHA256SUMS"
printf 'Cutover boundary passed; evidence written to %s\n' "$output_dir"
