#!/usr/bin/env bash
set -Eeuo pipefail

: "${REMOTE_BACKUP_URI:?Set the off-host backup locator}"
: "${BACKUP_DOWNLOAD_HOOK:?Set an executable download hook: locator output}"
: "${BACKUP_DECRYPT_HOOK:?Set an executable decrypt hook: input output}"
: "${EXPECTED_ALEMBIC_REVISION:?Set the expected database revision}"
for hook in "$BACKUP_DOWNLOAD_HOOK" "$BACKUP_DECRYPT_HOOK"; do
  [[ -x "$hook" ]] || { echo "hook is not executable: $hook" >&2; exit 2; }
done

postgres_image="${RESTORE_POSTGRES_IMAGE:-postgres:17-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193}"
container="beanly-restore-$RANDOM-$$"
workdir="$(mktemp -d)"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf -- "$workdir"; }
trap cleanup EXIT

encrypted="$workdir/backup.enc"
plain="$workdir/backup.dump"
"$BACKUP_DOWNLOAD_HOOK" "$REMOTE_BACKUP_URI" "$encrypted"
"$BACKUP_DECRYPT_HOOK" "$encrypted" "$plain"
[[ -s "$plain" ]] || { echo "download/decrypt produced no dump" >&2; exit 1; }

docker run -d --name "$container" -e POSTGRES_PASSWORD=restore-only -e POSTGRES_DB=beanly_restore "$postgres_image" >/dev/null
for _ in {1..60}; do
  docker exec "$container" pg_isready -U postgres -d beanly_restore >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$container" pg_isready -U postgres -d beanly_restore >/dev/null
docker cp "$plain" "$container:/tmp/backup.dump" >/dev/null
docker exec "$container" pg_restore --exit-on-error --no-owner -U postgres -d beanly_restore /tmp/backup.dump
revision="$(docker exec "$container" psql -At -U postgres -d beanly_restore -c 'select version_num from alembic_version')"
[[ "$revision" == "$EXPECTED_ALEMBIC_REVISION" ]] || { echo "revision mismatch: $revision" >&2; exit 1; }
docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d beanly_restore -c \
  "select count(*) as users from users; select count(*) as organizations from organizations;" >/dev/null

echo "restore drill passed for $REMOTE_BACKUP_URI at revision $revision"
