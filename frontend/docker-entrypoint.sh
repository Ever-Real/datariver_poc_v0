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

knowledge_document_timeout_seconds=${KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS:-135}
case "$knowledge_document_timeout_seconds" in
  ''|*[!0-9]*)
    echo "KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS must be an integer between 1 and 900." >&2
    exit 2
    ;;
esac
if [ "$knowledge_document_timeout_seconds" -lt 1 ] || [ "$knowledge_document_timeout_seconds" -gt 900 ]; then
  echo "KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS must be an integer between 1 and 900." >&2
  exit 2
fi
export KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS="$knowledge_document_timeout_seconds"

S3_PUBLIC_ORIGIN=${S3_PUBLIC_ORIGIN:-}
OIDC_PUBLIC_ORIGIN=${OIDC_PUBLIC_ORIGIN:-}
DATAHUB_EMBED_BASE_URL=${DATAHUB_EMBED_BASE_URL:-}
GRAFANA_EMBED_BASE_URL=${GRAFANA_EMBED_BASE_URL:-}
export S3_PUBLIC_ORIGIN OIDC_PUBLIC_ORIGIN DATAHUB_EMBED_BASE_URL GRAFANA_EMBED_BASE_URL

mkdir -p \
  /tmp/datariver \
  /tmp/nginx/conf.d \
  /tmp/nginx/client_temp \
  /tmp/nginx/proxy_temp \
  /tmp/nginx/fastcgi_temp \
  /tmp/nginx/uwsgi_temp \
  /tmp/nginx/scgi_temp

json_string() {
  printf '%s' "$1" | awk 'BEGIN { ORS = "" }
    {
      if (NR > 1) printf "\\n"
      gsub(/\\/, "\\\\")
      gsub(/\"/, "\\\"")
      gsub(/\r/, "\\r")
      printf "%s", $0
    }'
}

write_config_value() {
  name=$1
  value=$2
  printf '  %s: "' "$name"
  json_string "$value"
  printf '"'
}

runtime_config=/tmp/datariver/runtime-config.js
{
  printf 'window.__DATARIVER_CONFIG__ = Object.freeze({\n'
  write_config_value apiBaseUrl "${BROWSER_API_BASE_URL:-/api/v1}"
  printf ',\n'
  write_config_value oidcAuthority "${BROWSER_OIDC_AUTHORITY:-}"
  printf ',\n'
  write_config_value oidcClientId "${BROWSER_OIDC_CLIENT_ID:-datariver-web}"
  printf ',\n'
  write_config_value oidcRedirectUri "${BROWSER_OIDC_REDIRECT_URI:-}"
  printf ',\n'
  write_config_value oidcHighAssuranceAcr "${BROWSER_OIDC_HIGH_ASSURANCE_ACR:-2}"
  printf ',\n'
  write_config_value oidcPasswordReauthAcr "${BROWSER_OIDC_PASSWORD_REAUTH_ACR:-1}"
  printf '\n})\n'
} >"$runtime_config"
chmod 0444 "$runtime_config"

exec /docker-entrypoint.sh "$@"
