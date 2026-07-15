#!/usr/bin/env sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
host_gateway=$(ip route show default | awk 'NR == 1 { print $3 }')
case "$host_gateway" in
  ''|*[!0-9a-fA-F.:]*)
    echo "Could not determine the WSL host gateway." >&2
    exit 2
    ;;
esac

export DATARIVER_API_UPSTREAM=${DATARIVER_API_UPSTREAM:-"$host_gateway:8000"}
cd "$root"
docker compose \
  -f compose.yaml \
  -f compose.identity.yaml \
  -f compose.host-dev.yaml \
  -f compose.gateway.yaml \
  -f compose.gateway.host-dev.yaml \
  up -d --build --wait apisix

echo "APISIX is forwarding to $DATARIVER_API_UPSTREAM."
