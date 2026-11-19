#!/bin/sh
# Writes /config.js from environment variables, then starts nginx (K16: nothing is built in).
#   FRONTEND_API_BASE_URL      API base URL (default: /api, same origin through Traefik)
#   FRONTEND_OIDC_ISSUER       OIDC issuer URL (required)
#   FRONTEND_OIDC_CLIENT_ID    OIDC client id (default: dap-web)
#   FRONTEND_LANGFUSE_BASE_URL Langfuse base URL for trace links (default: empty, no link)
set -eu

CONFIG_FILE=/usr/share/nginx/runtime/config.js

# Prints the value as a double-quoted JavaScript string. `<` is escaped so that a value such as
# `</script>` cannot end a script element; control characters are refused.
js_string() {
  case "$1" in
    *[[:cntrl:]]*)
      echo "entrypoint: a value contains a control character" >&2
      exit 1
      ;;
  esac
  printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/</\\u003c/g')"
}

if [ -z "${FRONTEND_OIDC_ISSUER:-}" ]; then
  echo "entrypoint: FRONTEND_OIDC_ISSUER is required" >&2
  exit 1
fi

# Plain assignments, so that `set -e` stops the script when a value is refused.
api_base_url=$(js_string "${FRONTEND_API_BASE_URL:-/api}")
oidc_issuer=$(js_string "$FRONTEND_OIDC_ISSUER")
oidc_client_id=$(js_string "${FRONTEND_OIDC_CLIENT_ID:-dap-web}")
langfuse_base_url=$(js_string "${FRONTEND_LANGFUSE_BASE_URL:-}")

cat >"$CONFIG_FILE" <<EOF
// Generated at container start from environment variables (K16).
window.__CONFIG__ = {
  apiBaseUrl: $api_base_url,
  oidcIssuer: $oidc_issuer,
  oidcClientId: $oidc_client_id,
  langfuseBaseUrl: $langfuse_base_url,
};
EOF

exec nginx -g "daemon off;"
