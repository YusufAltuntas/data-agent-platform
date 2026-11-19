#!/usr/bin/env bash
# Creates or updates the Kubernetes Secret `dap-secrets` from .env (design §10, step 3).
# The keys are the ones listed in .env.example. With CI=true, missing values get random ones.
# Values are never printed.
set -euo pipefail

CONTEXT=kind-dap
NAMESPACE=dap
SECRET=dap-secrets
ENV_FILE=.env
EXAMPLE_FILE=.env.example

# Not secret (read by the Makefile) or allowed to stay empty (K5, K22).
NOT_SECRET=" PUBLIC_PORT "
OPTIONAL=" ANTHROPIC_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST "

kc() { kubectl --context "$CONTEXT" "$@"; }

# Value of KEY in .env (CR and surrounding quotes stripped); empty if absent.
env_value() {
  local line value
  [[ -f "$ENV_FILE" ]] || return 0
  line=$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)
  value=${line#*=}
  value=${value%$'\r'}
  if [[ $value =~ ^\"(.*)\"$ || $value =~ ^\'(.*)\'$ ]]; then
    value=${BASH_REMATCH[1]}
  fi
  printf '%s' "$value"
}

random_value() {
  case "$1" in
    DAP_FERNET_KEY) openssl rand -base64 32 | tr '+/' '-_' ;;   # urlsafe base64 of 32 bytes
    LITELLM_MASTER_KEY) printf 'sk-%s' "$(openssl rand -hex 24)" ;;  # LiteLLM wants an sk- prefix
    *) openssl rand -hex 24 ;;
  esac
}

if [[ ! -f "$ENV_FILE" && "${CI:-}" != "true" ]]; then
  echo "secrets.sh: $ENV_FILE not found (copy $EXAMPLE_FILE and fill it in)" >&2
  exit 1
fi

declare -A values=()
missing=()
for key in $(grep -oE '^[A-Z0-9_]+' "$EXAMPLE_FILE"); do
  [[ $NOT_SECRET == *" $key "* ]] && continue
  value=$(env_value "$key")
  if [[ -z $value && $OPTIONAL != *" $key "* ]]; then
    if [[ "${CI:-}" == "true" ]]; then
      value=$(random_value "$key")
    else
      missing+=("$key")
    fi
  fi
  values[$key]=$value
done

if ((${#missing[@]})); then
  echo "secrets.sh: empty in $ENV_FILE: ${missing[*]}" >&2
  exit 1
fi

: "${values[LANGFUSE_HOST]:=https://cloud.langfuse.com}"

# LiteLLM reads its database address as one URL; the password is URL-encoded.
encoded=$(jq -rn --arg v "${values[POSTGRES_PASSWORD]}" '$v | @uri')
values[LITELLM_DATABASE_URL]="postgresql://postgres:${encoded}@postgres:5432/litellm"

args=()
for key in "${!values[@]}"; do
  args+=("--from-literal=$key=${values[$key]}")
done

kc create namespace "$NAMESPACE" --dry-run=client -o yaml | kc apply --server-side -f - >/dev/null
# Server-side apply: no last-applied annotation holding a copy of the data.
kc -n "$NAMESPACE" create secret generic "$SECRET" "${args[@]}" --dry-run=client -o yaml \
  | kc apply --server-side --force-conflicts -f - >/dev/null
echo "secrets.sh: secret $NAMESPACE/$SECRET applied (${#values[@]} keys)"
