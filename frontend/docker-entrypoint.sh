#!/bin/sh
set -eu

mkdir -p \
  /tmp/nginx/conf.d \
  /tmp/nginx/client_temp \
  /tmp/nginx/proxy_temp \
  /tmp/nginx/fastcgi_temp \
  /tmp/nginx/uwsgi_temp \
  /tmp/nginx/scgi_temp

exec /docker-entrypoint.sh "$@"
