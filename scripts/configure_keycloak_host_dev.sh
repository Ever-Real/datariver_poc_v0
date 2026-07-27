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

sync_output=$(
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
  jihoon_id=
  sua_id=
  minjae_id=
  for fixture in \
    "jihoon.choi|지훈|최|jihoon.choi@localhost.invalid" \
    "sua.han|수아|한|sua.han@localhost.invalid" \
    "minjae.oh|민재|오|minjae.oh@localhost.invalid"
  do
    IFS="|" read -r username first_name last_name email <<EOF
$fixture
EOF
    user_id=$(
      /opt/keycloak/bin/kcadm.sh get users \
        --config "$config" -r datariver -q "username=$username" \
        --fields id --format csv --noquotes
    )
    if [ -z "$user_id" ]; then
      demo_password=$(cat /run/secrets/keycloak_demo_password)
      /opt/keycloak/bin/kcadm.sh create users \
        --config "$config" -r datariver \
        -s "username=$username" \
        -s "firstName=$first_name" -s "lastName=$last_name" \
        -s "email=$email" -s emailVerified=true -s enabled=true \
        -s "requiredActions=[\"UPDATE_PASSWORD\"]" \
        -s "credentials=[{\"type\":\"password\",\"value\":\"$demo_password\",\"temporary\":true}]" \
        >/dev/null
      unset demo_password
      user_id=$(
        /opt/keycloak/bin/kcadm.sh get users \
          --config "$config" -r datariver -q "username=$username" \
          --fields id --format csv --noquotes
      )
    else
      /opt/keycloak/bin/kcadm.sh update "users/$user_id" \
        --config "$config" -r datariver \
        -s "firstName=$first_name" -s "lastName=$last_name" \
        -s "email=$email" -s emailVerified=true -s enabled=true >/dev/null
    fi
    test -n "$user_id"
    case "$username" in
      jihoon.choi) jihoon_id=$user_id ;;
      sua.han) sua_id=$user_id ;;
      minjae.oh) minjae_id=$user_id ;;
    esac
  done
  test -n "$jihoon_id"
  test -n "$sua_id"
  test -n "$minjae_id"
  printf "__DATARIVER_DEMO_IDENTITIES__%s|%s|%s\n" \
    "$jihoon_id" "$sua_id" "$minjae_id"
' -- "$web_origin"
)

printf '%s\n' "$sync_output" | sed '/^__DATARIVER_DEMO_IDENTITIES__/d'
identity_state=$(
  printf '%s\n' "$sync_output" |
    sed -n 's/^__DATARIVER_DEMO_IDENTITIES__//p' |
    tail -n 1
)
IFS="|" read -r jihoon_id sua_id minjae_id extra <<EOF
$identity_state
EOF
for user_id in "$jihoon_id" "$sua_id" "$minjae_id"
do
  case "$user_id" in
    ""|*[!0-9a-fA-F-]*)
      echo "Keycloak returned an invalid local demo identity id." >&2
      exit 3
      ;;
  esac
  if [ "${#user_id}" -ne 36 ]; then
    echo "Keycloak returned an invalid local demo identity id." >&2
    exit 3
  fi
done
if [ -n "${extra:-}" ]; then
  echo "Keycloak returned an invalid local demo identity state." >&2
  exit 3
fi

state_directory="$root/runtime/identity"
state_file="$state_directory/local-demo-identities.json"
state_tmp="$state_file.tmp.$$"
mkdir -p "$state_directory"
trap 'rm -f "$state_tmp"' EXIT HUP INT TERM
(
  umask 077
  printf '{"jihoon.choi":"%s","sua.han":"%s","minjae.oh":"%s"}\n' \
    "$jihoon_id" "$sua_id" "$minjae_id" >"$state_tmp"
)
mv "$state_tmp" "$state_file"
trap - EXIT HUP INT TERM

echo "Keycloak web redirects, login theme, governed identity client and local demo identities configured for $web_origin."
