#!/usr/bin/env bash
set -Eeuo pipefail

: "${ENV_FILE:?Set ENV_FILE to the protected production env file}"
: "${ROLLBACK_GIT_SHA:?Set the previously verified release SHA}"
[[ "$ROLLBACK_GIT_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "ROLLBACK_GIT_SHA must be 40 lowercase hex characters" >&2; exit 2; }

export GIT_SHA="$ROLLBACK_GIT_SHA"
compose=(docker compose --env-file "$ENV_FILE" -f compose.production.yaml)
"${compose[@]}" pull api frontend worker outbox-worker integration-worker
"${compose[@]}" up -d --no-deps --wait api frontend worker outbox-worker integration-worker reverse-proxy
python3 scripts/smoke.py

echo "application rolled back to $GIT_SHA; schema was not downgraded"
