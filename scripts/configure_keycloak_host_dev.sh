#!/usr/bin/env sh
set -eu

container=${DATARIVER_KEYCLOAK_CONTAINER:-datariver-next-keycloak-1}
web_origin=${DATARIVER_WEB_ORIGIN:-http://localhost:5173}

case "$web_origin" in
  http://localhost:[0-9]*) ;;
  *)
    echo "DATARIVER_WEB_ORIGIN must be an http://localhost:<port> origin." >&2
    exit 2
    ;;
esac

docker exec "$container" bash -ec '
  config=/tmp/kcadm-host-dev.config
  web_origin=$1
  /opt/keycloak/bin/kcadm.sh config credentials \
    --config "$config" \
    --server http://127.0.0.1:8080 \
    --realm master \
    --user datariver-bootstrap \
    --password "$(cat /run/secrets/keycloak_admin_password)" >/dev/null
  client_id=$(
    /opt/keycloak/bin/kcadm.sh get clients \
      --config "$config" \
      -r datariver \
      -q clientId=datariver-web \
      --fields id \
      --format csv \
      --noquotes
  )
  test -n "$client_id"
  /opt/keycloak/bin/kcadm.sh update "clients/$client_id" \
    --config "$config" \
    -r datariver \
    -s "redirectUris=[\"$web_origin/*\"]" \
    -s "webOrigins=[\"$web_origin\"]" \
    -s "attributes={\"pkce.code.challenge.method\":\"S256\",\"post.logout.redirect.uris\":\"$web_origin/*\"}" \
    >/dev/null
  /opt/keycloak/bin/kcadm.sh update realms/datariver \
    --config "$config" \
    -s "loginTheme=datariver" \
    >/dev/null
' -- "$web_origin"

echo "Keycloak datariver-web redirects and DataRiver login theme configured for $web_origin."
