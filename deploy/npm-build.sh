#!/bin/sh
# Build-stage-only npm settings. No runtime provider configuration is read.
set -eu
export NPM_CONFIG_USERCONFIG=/tmp/datariver-npmrc
trap 'rm -f "$NPM_CONFIG_USERCONFIG"' EXIT HUP INT TERM
npm_proxy="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}"
proxy_state=ABSENT
if [ -n "$npm_proxy" ]; then
  proxy_state=SET
  npm config set proxy "$npm_proxy"
  npm config set https-proxy "$npm_proxy"
  # Preserve the existing PREP build proxy contract, scoped to this RUN only.
  npm config set strict-ssl false
fi
printf 'NPM_BUILD|stage=%s|node=%s|npm=%s|proxy=%s\n' "$1" "$(node --version)" "$(npm --version)" "$proxy_state"
npm "$@"
