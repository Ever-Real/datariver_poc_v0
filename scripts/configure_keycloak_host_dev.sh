#!/usr/bin/env sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
container=${DATARIVER_KEYCLOAK_CONTAINER:-datariver-next-keycloak-1}
demo_password_file="$root/secrets/keycloak_demo_password"
web_origin=${DATARIVER_WEB_ORIGIN:-}
if [ -z "$web_origin" ] && [ -f "$root/.env" ]; then
  web_origin=$(sed -n 's/^APP_PUBLIC_ORIGIN=//p' "$root/.env" | tail -n 1)
fi
web_origin=${web_origin:-http://localhost:38102}

case "$web_origin" in
  http://localhost:[0-9]*) ;;
  *)
    echo "DATARIVER_WEB_ORIGIN must be an http://localhost:<port> origin." >&2
    exit 2
    ;;
esac
[ -s "$demo_password_file" ] || {
  echo "Missing development password file: $demo_password_file" >&2
  exit 2
}

docker exec -i "$container" bash -ec '
  config=/tmp/kcadm-host-dev.config
  web_origin=$1
  IFS= read -r demo_password || [ -n "$demo_password" ]
  trap '\''rm -f "$config"'\'' EXIT
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
  identity_client_id=$(
    /opt/keycloak/bin/kcadm.sh get clients \
      --config "$config" -r datariver \
      -q clientId=datariver-identity-admin --fields id --format csv --noquotes
  )
  identity_secret=$(cat /run/secrets/keycloak_identity_admin_client_secret)
  if [ -z "$identity_client_id" ]; then
    /opt/keycloak/bin/kcadm.sh create clients \
      --config "$config" -r datariver \
      -s clientId=datariver-identity-admin \
      -s name="DataRiver governed identity administration" \
      -s enabled=true -s publicClient=false \
      -s standardFlowEnabled=false -s directAccessGrantsEnabled=false \
      -s implicitFlowEnabled=false -s serviceAccountsEnabled=true \
      -s "secret=$identity_secret" >/dev/null
    identity_client_id=$(
      /opt/keycloak/bin/kcadm.sh get clients \
        --config "$config" -r datariver \
        -q clientId=datariver-identity-admin --fields id --format csv --noquotes
    )
  else
    /opt/keycloak/bin/kcadm.sh update "clients/$identity_client_id" \
      --config "$config" -r datariver \
      -s enabled=true -s publicClient=false \
      -s standardFlowEnabled=false -s directAccessGrantsEnabled=false \
      -s implicitFlowEnabled=false -s serviceAccountsEnabled=true \
      -s "secret=$identity_secret" >/dev/null
  fi
  test -n "$identity_client_id"
  identity_user_id=$(
    /opt/keycloak/bin/kcadm.sh get "clients/$identity_client_id/service-account-user" \
      --config "$config" -r datariver --fields id --format csv --noquotes
  )
  test -n "$identity_user_id"
  /opt/keycloak/bin/kcadm.sh add-roles \
    --config "$config" -r datariver --uid "$identity_user_id" \
    --cclientid realm-management \
    --rolename manage-users --rolename view-users --rolename query-users >/dev/null
  /opt/keycloak/bin/kcadm.sh set-password \
    --config "$config" -r datariver \
    --username datariver-admin \
    --new-password "$demo_password" \
    --temporary=false >/dev/null
  unset demo_password
' -- "$web_origin" < "$demo_password_file"

echo "Keycloak web redirects, login theme, identity client and development login synchronized for $web_origin."
