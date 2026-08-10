#!/usr/bin/env bash
set -Eeuo pipefail

: "${ENV_FILE:?Set ENV_FILE to the protected production env file}"
: "${GIT_SHA:?Export the exact 40-character release SHA}"
: "${RECOVERY_POINT_HOOK:?Set an executable hook that creates and verifies a recovery point}"

[[ "$GIT_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "GIT_SHA must be 40 lowercase hex characters" >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "ENV_FILE does not exist: $ENV_FILE" >&2; exit 2; }
[[ -x "$RECOVERY_POINT_HOOK" ]] || { echo "RECOVERY_POINT_HOOK is not executable" >&2; exit 2; }

compose=(docker compose --env-file "$ENV_FILE" -f compose.production.yaml)
python3 scripts/verify_compose.py compose.production.yaml --env-file "$ENV_FILE"
"$RECOVERY_POINT_HOOK" "$GIT_SHA"
"${compose[@]}" pull
"${compose[@]}" --profile tools run --rm migrate
"${compose[@]}" up -d --remove-orphans --wait
python3 scripts/smoke.py

echo "deployed and smoke-tested $GIT_SHA"
