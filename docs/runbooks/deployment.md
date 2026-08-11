# Deployment

## Before change

Confirm CI is green for the exact commit, both GHCR images exist at that 40-character SHA, the migration follows `0018_integrations`, certificates are valid, telemetry/alerts are receiving staging data, database capacity fits the documented budget and rollback SHA is known. Announce the change window.

Validate the protected env without starting containers:

```bash
export ENV_FILE=/etc/beanly/production.env
export GIT_SHA=<40-character-sha>
python3 scripts/verify_compose.py compose.production.yaml --env-file "$ENV_FILE"
```

Confirm the rendered model publishes no port except reverse-proxy 80/443. Check image references contain the intended SHA or a real non-zero manifest digest.

## Deploy

Configure `RECOVERY_POINT_HOOK` to create and verify a fresh recovery point before migration. Configure `SMOKE_BASE_URL`, `SMOKE_EMAIL` and `SMOKE_PASSWORD` for the dedicated internal organization, then run:

```bash
export RECOVERY_POINT_HOOK=/etc/beanly/hooks/create-recovery-point
export SMOKE_BASE_URL=https://beanly.example.com
export SMOKE_EMAIL=synthetic-smoke@example.com
export SMOKE_PASSWORD='<secret>'
./scripts/deploy.sh
```

The script verifies Compose, verifies the recovery hook, pulls immutable images, runs the migration once, starts services with readiness waiting and runs read-only smoke tests. It never builds on the host and never runs `compose down`.

## Verify

```bash
docker compose --env-file "$ENV_FILE" -f compose.production.yaml ps
docker compose --env-file "$ENV_FILE" -f compose.production.yaml logs --since 10m api outbox-worker integration-worker
```

Confirm `/health/version` reports the intended SHA, readiness is healthy, smoke passed, migration head is `0019_production_hardening`, 5xx/429/DB pool and queue-age metrics are normal and no new dead letters exist.

## Failure

Stop the rollout. Do not automatically downgrade the schema. If the previous application is compatible with the expanded schema, follow [rollback](rollback.md). If migration or data integrity is uncertain, remove traffic and follow [database restore](database-restore.md). Preserve request IDs, logs and the release/recovery-point identifiers.
