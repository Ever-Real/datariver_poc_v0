#!/usr/bin/env sh
set -eu

network=${DATARIVER_CONNECTOR_NETWORK-datariver-connectors}
case "$network" in
  ''|-*|.|..|*[!A-Za-z0-9_.-]*)
    echo "DATARIVER_CONNECTOR_NETWORK contains unsupported characters." >&2
    exit 2
    ;;
esac

if docker network inspect "$network" >/dev/null 2>&1; then
  exit 0
fi

if docker network create --driver bridge "$network" >/dev/null 2>&1; then
  echo "Created connector network: $network"
  exit 0
fi

# A concurrent bootstrap may have created the same external network after our
# first inspect. Reuse it, but fail closed for every other Docker error.
if docker network inspect "$network" >/dev/null 2>&1; then
  exit 0
fi
echo "Could not create connector network: $network" >&2
exit 1
