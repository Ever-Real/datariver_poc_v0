#!/usr/bin/env sh
set -eu

network=${DATARIVER_CONNECTOR_NETWORK:-datariver-connectors}
case "$network" in
  ''|*[!A-Za-z0-9_.-]*)
    echo "DATARIVER_CONNECTOR_NETWORK contains unsupported characters." >&2
    exit 2
    ;;
esac

if docker network inspect "$network" >/dev/null 2>&1; then
  exit 0
fi

docker network create --driver bridge "$network" >/dev/null
echo "Created connector network: $network"
