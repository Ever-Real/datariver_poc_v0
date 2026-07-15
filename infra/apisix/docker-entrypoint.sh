#!/usr/bin/env sh
set -eu

# APISIX renders nginx.conf at startup. Restore the immutable image defaults into
# the writable, memory-backed /usr/local/apisix/conf mount before applying the
# declarative DataRiver configuration.
cp -a /opt/apisix-conf-dist/. /usr/local/apisix/conf/
cp /opt/datariver/apisix/config.yaml /usr/local/apisix/conf/config.yaml
api_upstream=${DATARIVER_API_UPSTREAM:-api:8000}
case "$api_upstream" in
  ''|*[!A-Za-z0-9._:-]*)
    echo "DATARIVER_API_UPSTREAM must be a host:port value." >&2
    exit 2
    ;;
esac
sed "s/__DATARIVER_API_UPSTREAM__/$api_upstream/g" \
  /opt/datariver/apisix/apisix.yaml > /usr/local/apisix/conf/apisix.yaml

exec /docker-entrypoint.sh "$@"
