#!/bin/sh
set -eu

api_proxy_read_timeout_seconds=${API_PROXY_READ_TIMEOUT_SECONDS:-30}
case "$api_proxy_read_timeout_seconds" in
  ''|*[!0-9]*)
    echo "API_PROXY_READ_TIMEOUT_SECONDS must be an integer between 1 and 900." >&2
    exit 2
    ;;
esac
if [ "$api_proxy_read_timeout_seconds" -lt 1 ] || [ "$api_proxy_read_timeout_seconds" -gt 900 ]; then
  echo "API_PROXY_READ_TIMEOUT_SECONDS must be an integer between 1 and 900." >&2
  exit 2
fi
export API_PROXY_READ_TIMEOUT_SECONDS="$api_proxy_read_timeout_seconds"

mkdir -p \
  /tmp/nginx/conf.d \
  /tmp/nginx/client_temp \
  /tmp/nginx/proxy_temp \
  /tmp/nginx/fastcgi_temp \
  /tmp/nginx/uwsgi_temp \
  /tmp/nginx/scgi_temp

exec /docker-entrypoint.sh "$@"
