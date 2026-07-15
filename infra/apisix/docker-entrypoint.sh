#!/usr/bin/env sh
set -eu

# APISIX renders nginx.conf at startup. Restore the immutable image defaults into
# the writable, memory-backed /usr/local/apisix/conf mount before applying the
# declarative DataRiver configuration.
cp -a /opt/apisix-conf-dist/. /usr/local/apisix/conf/
cp /opt/datariver/apisix/config.yaml /usr/local/apisix/conf/config.yaml
cp /opt/datariver/apisix/apisix.yaml /usr/local/apisix/conf/apisix.yaml

exec /docker-entrypoint.sh "$@"
