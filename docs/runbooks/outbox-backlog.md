# Outbox backlog or dead letters

Core sales, payments and inventory writes continue because the outbox is durable in PostgreSQL. Finance and analytics projections can be temporarily stale.

Inspect counts and oldest age without changing rows:

```sql
select count(*) as pending, extract(epoch from now()-min(available_at))::int as oldest_seconds
from outbox_events where processed_at is null and dead_lettered_at is null;
select event_name, count(*) from outbox_events where dead_lettered_at is not null group by 1 order by 2 desc;
```

Check `beanly-outbox-worker` logs/metrics by request/event ID, PostgreSQL health, lock waits and handler failures. Restart a crashed worker once after fixing the dependency. Let its lease/retry logic reclaim work; do not clear `locked_by`, mark rows processed or bulk retry directly in SQL.

Verify pending age decreases, dead-letter count does not grow and finance/analytics totals converge with operational payment facts. For a persistent poison event, preserve payload metadata without exposing secrets, fix/test the handler, then use an audited targeted replay procedure.
