# PostgreSQL unavailable

## Detect and contain

Symptoms: readiness fails, DB pool/connection errors rise, workers stop making progress. Freeze deployments and manual retries. Do not redirect writes to Redis and do not restart every service simultaneously.

Check host/provider status, disk, connections, long transactions and blockers. For local Compose:

```bash
docker compose --env-file "$ENV_FILE" -f compose.production.yaml ps postgres
docker compose --env-file "$ENV_FILE" -f compose.production.yaml logs --since 15m postgres api
docker compose --env-file "$ENV_FILE" -f compose.production.yaml exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select state,wait_event_type,wait_event,count(*) from pg_stat_activity group by 1,2,3"'
```

## Recover

If capacity/locks are the cause, cancel only the identified offending query after preserving its text, owner and request ID. If storage or corruption is suspected, stop writes and use [database restore](database-restore.md). Do not repeatedly restart PostgreSQL or delete its volume.

After recovery, wait for readiness, run the synthetic smoke test, verify migration head, then watch payment/inventory invariants, outbox/integration queue age, dead letters and DB saturation until backlogs drain.
