#!/usr/bin/env bash
# End-to-end checks against the running kind cluster (design §11, E2E row), with the fake model
# only (K22). Prints every check as `ok` or `FAIL` and exits non-zero if any check failed.
# Passwords and tokens are never printed and never put on a command line.
set -euo pipefail

CONTEXT=kind-dap
NAMESPACE=dap
SECRET=dap-secrets
PUBLIC_PORT=${PUBLIC_PORT:-80}
SLOW_STEP_DELAY_S=20  # the worker-death run: two delayed steps, ~40 s per attempt
RUN_TIMEOUT_S=120
SLOW_RUN_TIMEOUT_S=420
API_WAIT_S=60

suffix=$([[ $PUBLIC_PORT == 80 ]] || printf ':%s' "$PUBLIC_PORT")
APP="http://app.localhost$suffix"
API="$APP/api"
TOKEN_URL="http://auth.localhost$suffix/realms/dap/protocol/openid-connect/token"

kc() { kubectl --context "$CONTEXT" -n "$NAMESPACE" "$@"; }

tmp=$(mktemp -d)
worker_slowed=false
# Runs on every exit; the temp directory (token header files) goes even if restoring fails.
cleanup() {
  rm -rf "$tmp"
  if $worker_slowed; then
    echo "restoring the worker's default settings"
    kc set env deployment/worker FAKE_STEP_DELAY_S- >/dev/null \
      && kc rollout status deployment/worker --timeout=180s >/dev/null \
      || {
        echo "smoke.sh: could not restore the worker; run" \
          "'kubectl --context $CONTEXT -n $NAMESPACE set env deployment/worker FAKE_STEP_DELAY_S-'" >&2
        exit 1  # in the EXIT trap this sets the script's exit status, even if every check passed
      }
  fi
}
trap cleanup EXIT

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() {
  printf 'FAIL  %s%s\n' "$1" "${2:+: $2}"
  failures=$((failures + 1))
}

# K22: never spend money. The platform chart's ConfigMap says which provider the worker uses.
provider=$(kc get configmap platform-config -o 'jsonpath={.data.LLM_PROVIDER}')
if [[ $provider != fake ]]; then
  echo "smoke.sh: the cluster runs the real model (LLM_PROVIDER=$provider); run 'make up' first" >&2
  exit 2
fi

# DNS fallback: a resolver that does not map *.localhost to loopback (curl exit code 6).
resolve=()
code=0
curl -s -o /dev/null --max-time 10 "$API/healthz" || code=$?
if ((code == 6)); then
  echo "*.localhost does not resolve here; using curl --resolve to 127.0.0.1"
  resolve=(--resolve "app.localhost:$PUBLIC_PORT:127.0.0.1"
    --resolve "auth.localhost:$PUBLIC_PORT:127.0.0.1")
fi

# Writes the user's Authorization header to a file (password grant on the dap-smoke client).
login() {
  local user=$1 password token
  password=$(kc get secret "$SECRET" -o "jsonpath={.data.DAP_${user^^}_PASSWORD}" | base64 -d)
  token=$(printf '%s' "$password" | curl -s "${resolve[@]}" "$TOKEN_URL" \
    -d grant_type=password -d client_id=dap-smoke -d "username=$user" \
    --data-urlencode password@- | jq -r '.access_token // empty')
  [[ -n $token ]] || return 1
  printf 'Authorization: Bearer %s' "$token" >"$tmp/auth-$user"
}

# api METHOD PATH USER [JSON]: sets STATUS and BODY. USER "-" sends no token.
api() {
  local method=$1 path=$2 user=$3 data=${4:-}
  local args=(-s "${resolve[@]}" -o "$tmp/body" -w '%{http_code}' -X "$method")
  [[ $user == - ]] || args+=(-H "@$tmp/auth-$user")
  [[ -z $data ]] || args+=(-H 'Content-Type: application/json' -d "$data")
  STATUS=$(curl "${args[@]}" "$API$path") || STATUS=000
  BODY=$(cat "$tmp/body" 2>/dev/null || true)
}

# wait_run RUN_ID TIMEOUT_S JQ_FILTER: polls the run (as alice) until the filter holds.
wait_run() {
  local deadline=$((SECONDS + $2))
  while ((SECONDS < deadline)); do
    api GET "/runs/$1" alice
    if [[ $STATUS == 200 ]] && jq -e "$3" <<<"$BODY" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

run_summary() { jq -c '{status, attempts, error}' <<<"$BODY" 2>/dev/null || echo "HTTP $STATUS"; }

start_run() {
  api POST /teams/sales/runs alice \
    '{"dataset": "sales", "question": "How many rows does the first table have?"}'
  RUN_ID=$(jq -r '.run_id // empty' <<<"$BODY" 2>/dev/null || true)
  [[ $STATUS == 202 && -n $RUN_ID ]]
}

# --- Routing (K16) ---
# Right after `make up` Traefik can still answer 502/504 while the new API pod takes over.
deadline=$((SECONDS + API_WAIT_S))
api GET /healthz -
while [[ $STATUS != 200 ]] && ((SECONDS < deadline)); do
  sleep 2
  api GET /healthz -
done
[[ $STATUS == 200 ]] && pass "API reachable through Traefik (/api/healthz 200)" \
  || fail "API reachable through Traefik (/api/healthz 200)" "HTTP $STATUS"

# The API serves /api/metrics, so the 404 must be Traefik's (no route), not the API's JSON one.
api GET /metrics -
[[ $STATUS == 404 && $BODY == "404 page not found" ]] \
  && pass "/api/metrics not exposed outside the cluster (Traefik 404)" \
  || fail "/api/metrics not exposed outside the cluster (Traefik 404)" "HTTP $STATUS"

# --- Frontend (K16): the same origin serves the SPA and its runtime config.js ---
# web PATH: sets STATUS, CTYPE and BODY for a path on the app origin outside /api.
web() {
  local out
  out=$(curl -s "${resolve[@]}" -o "$tmp/body" -w '%{http_code} %{content_type}' "$APP$1") \
    || out=000
  STATUS=${out%% *}
  CTYPE=${out#* }
  BODY=$(cat "$tmp/body" 2>/dev/null || true)
}

web /
[[ $STATUS == 200 && $CTYPE == text/html* && $BODY == *'<div id="root">'* ]] \
  && pass "home page served (/ 200, HTML)" \
  || fail "home page served (/ 200, HTML)" "HTTP $STATUS $CTYPE"

web /config.js
[[ $STATUS == 200 && $BODY == *"oidcIssuer: \"http://auth.localhost$suffix/realms/dap\""* \
  && $BODY == *'oidcClientId: "dap-web"'* ]] \
  && pass "config.js: issuer for port $PUBLIC_PORT, client id dap-web" \
  || fail "config.js: issuer for port $PUBLIC_PORT, client id dap-web" "HTTP $STATUS"

# --- Tokens (direct grant, dap-smoke client only) ---
for user in alice bob carol; do
  if login "$user"; then
    pass "token for $user (password grant, dap-smoke)"
  else
    fail "token for $user (password grant, dap-smoke)"
    echo "smoke.sh: cannot continue without tokens" >&2
    exit 1
  fi
done

api GET /me alice
if [[ $STATUS == 200 ]] && jq -e '.teams | any(.id == "sales" and .role == "analyst")' \
  <<<"$BODY" >/dev/null; then
  pass "alice's token is accepted: analyst in sales (/api/me)"
else
  fail "alice's token is accepted: analyst in sales (/api/me)" "HTTP $STATUS"
fi

# --- Authorization (design §6); none of these counts against the rate limit ---
api POST /teams/sales/runs bob '{"dataset": "sales", "question": "How many orders?"}'
[[ $STATUS == 403 ]] && pass "bob (viewer) cannot start a run (403)" \
  || fail "bob (viewer) cannot start a run (403)" "HTTP $STATUS"

api POST /teams/sales/runs alice '{"dataset": "hr", "question": "How many employees?"}'
[[ $STATUS == 403 ]] && pass "alice cannot use the hr dataset in sales (403)" \
  || fail "alice cannot use the hr dataset in sales (403)" "HTTP $STATUS"

api POST /teams/hr/runs alice '{"dataset": "hr", "question": "How many employees?"}'
[[ $STATUS == 404 ]] && pass "alice cannot reach the hr team (404)" \
  || fail "alice cannot reach the hr team (404)" "HTTP $STATUS"

# --- Bootstrap's LiteLLM step: the team budget is read from LiteLLM (K4) ---
api GET /teams/hr/budget carol
if [[ $STATUS == 200 ]] && jq -e '.max_budget_usd > 0' <<<"$BODY" >/dev/null; then
  pass "hr team has a LiteLLM budget (carol, /api/teams/hr/budget)"
else
  fail "hr team has a LiteLLM budget (carol, /api/teams/hr/budget)" "HTTP $STATUS"
fi

# --- A run end to end (fake model) ---
if start_run; then
  if wait_run "$RUN_ID" "$RUN_TIMEOUT_S" '.status == "succeeded" and .attempts == 1'; then
    pass "alice's run succeeds"
  else
    fail "alice's run succeeds" "$(run_summary)"
  fi
else
  fail "alice's run succeeds" "create: HTTP $STATUS"
fi

# --- Worker death (K10, K11): a run killed mid-way is redelivered and restarts as attempt 2 ---
worker_slowed=true  # set first: an interruption right after `set env` still restores the worker
kc set env deployment/worker "FAKE_STEP_DELAY_S=$SLOW_STEP_DELAY_S" >/dev/null
kc rollout status deployment/worker --timeout=180s >/dev/null
check="worker killed mid-run: the run ends succeeded with attempts=2"
if ! start_run; then
  fail "$check" "create: HTTP $STATUS"
elif ! wait_run "$RUN_ID" 90 '.status == "running"'; then
  fail "$check" "never started: $(run_summary)"
else
  kc delete pod -l app.kubernetes.io/name=worker --grace-period=0 --force >/dev/null 2>&1
  if wait_run "$RUN_ID" "$SLOW_RUN_TIMEOUT_S" '.status != "queued" and .status != "running"' \
    && jq -e '.status == "succeeded" and .attempts == 2' <<<"$BODY" >/dev/null; then
    pass "$check"
  else
    fail "$check" "$(run_summary)"
  fi
fi

echo
if ((failures)); then
  echo "smoke: $failures check(s) failed"
  exit 1
fi
echo "smoke: all checks passed"
