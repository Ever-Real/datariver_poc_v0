#!/usr/bin/env sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
container=${DATARIVER_KEYCLOAK_CONTAINER:-datariver-next-keycloak-1}
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

docker exec "$container" bash -ec '
  config=/tmp/kcadm-host-dev.config
  web_origin=$1
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
    -s "attributes.\"pkce.code.challenge.method\"=\"S256\"" \
    -s "attributes.\"post.logout.redirect.uris\"=\"$web_origin/*\"" \
    -s "attributes.\"default.acr.values\"=\"1\"" \
    >/dev/null
  /opt/keycloak/bin/kcadm.sh update realms/datariver \
    --config "$config" \
    -s "loginTheme=datariver" \
    >/dev/null
  airflow_client_id=$(
    /opt/keycloak/bin/kcadm.sh get clients \
      --config "$config" -r datariver \
      -q clientId=datariver-airflow --fields id --format csv --noquotes
  )
  test -n "$airflow_client_id"
  /opt/keycloak/bin/kcadm.sh update "clients/$airflow_client_id" \
    --config "$config" -r datariver \
    -s enabled=true -s publicClient=false \
    -s standardFlowEnabled=false -s directAccessGrantsEnabled=false \
    -s implicitFlowEnabled=false -s serviceAccountsEnabled=true \
    -s "secret=$(cat /run/secrets/airflow_client_secret)" >/dev/null
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
' -- "$web_origin"

echo "Keycloak web redirects, login theme and governed identity client configured for $web_origin."
