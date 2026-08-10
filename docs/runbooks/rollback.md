# Application rollback

Rollback uses the previous immutable image and does not run `alembic downgrade`. Expand/contract migrations must keep release N-1 compatible with schema N.

## Procedure

Confirm the incident is caused by application code, identify the last verified SHA and verify its two GHCR images still exist. Then:

```bash
export ENV_FILE=/etc/beanly/production.env
export ROLLBACK_GIT_SHA=<previous-40-character-sha>
export SMOKE_BASE_URL=https://beanly.example.com
export SMOKE_EMAIL=synthetic-smoke@example.com
export SMOKE_PASSWORD='<secret>'
./scripts/rollback.sh
```

The script pulls and replaces application/worker images only, leaves PostgreSQL/Redis and schema untouched, waits for health and runs read-only smoke tests.

Verify `/health/version`, payment idempotency, error rate, database locks and queue age. If the old release is not schema-compatible, do not improvise a downgrade: remove traffic, preserve evidence and use the tested database recovery plan. Re-deploy the fixed SHA through the normal deployment procedure.
