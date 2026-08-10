# Redis unavailable

Redis is ephemeral infrastructure, not the source of truth. Orders, payments, inventory, finance, outbox, integration jobs and inbox events remain in PostgreSQL.

Sensitive login/OAuth operations fail closed while the shared limiter is unavailable. Safe reads may continue according to application policy; Celery work and rate-limit counters are disrupted.

```bash
docker compose --env-file "$ENV_FILE" -f compose.production.yaml ps redis
docker compose --env-file "$ENV_FILE" -f compose.production.yaml logs --since 15m redis api worker
docker compose --env-file "$ENV_FILE" -f compose.production.yaml exec redis redis-cli ping
```

Fix host memory/disk/network or replace the Redis container using the same protected credential. Do not restore Redis from a stale snapshot as business truth. After recovery verify login rate limits across two API instances, `429` includes `Retry-After`, Celery resumes and PostgreSQL queues remain consistent. Rotate the Redis password only through a coordinated env update/redeploy.
