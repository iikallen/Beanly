#!/usr/bin/env bash
set -Eeuo pipefail

: "${DATABASE_URL:?Set DATABASE_URL}"
: "${BACKUP_ENCRYPT_HOOK:?Set an executable encryption hook: input output}"
: "${BACKUP_UPLOAD_HOOK:?Set an executable off-host upload hook: file sha256}"
: "${BACKUP_VERIFY_HOOK:?Set an executable remote verification hook: locator sha256}"
for hook in "$BACKUP_ENCRYPT_HOOK" "$BACKUP_UPLOAD_HOOK" "$BACKUP_VERIFY_HOOK"; do
  [[ -x "$hook" ]] || { echo "hook is not executable: $hook" >&2; exit 2; }
done

workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain="$workdir/beanly-$timestamp.dump"
encrypted="$workdir/beanly-$timestamp.dump.enc"

pg_dump --dbname "$DATABASE_URL" --format=custom --no-owner --file "$plain"
"$BACKUP_ENCRYPT_HOOK" "$plain" "$encrypted"
[[ -s "$encrypted" ]] || { echo "encryption hook produced no backup" >&2; exit 1; }
rm -f -- "$plain"
digest="$(sha256sum "$encrypted" | awk '{print $1}')"
locator="$("$BACKUP_UPLOAD_HOOK" "$encrypted" "$digest")"
[[ -n "$locator" ]] || { echo "upload hook returned no remote locator" >&2; exit 1; }
"$BACKUP_VERIFY_HOOK" "$locator" "$digest"

echo "verified off-host backup: $locator sha256=$digest"
