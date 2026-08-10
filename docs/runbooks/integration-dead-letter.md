# Integration dead letter

An integration worker outage must not roll back the core sale. Fiscal/delivery work remains durable and pending unless a jurisdiction-specific policy explicitly requires synchronous fiscalization.

Inspect safely:

```sql
select provider_code, status, count(*) from integration_connections group by 1,2 order by 1,2;
select job_type, last_error_code, count(*) from integration_jobs where status='DEAD' group by 1,2 order by 3 desc;
select min(created_at) as oldest, count(*) from integration_jobs where status in ('PENDING','RETRYING');
```

Correlate the job, attempts and provider request ID. Never print ciphertext, OAuth tokens, webhook signatures or raw provider secrets. Determine temporary provider outage versus permanent credentials/configuration failure. Fix the cause before retrying through the Owner/Admin API; do not mutate status/attempts in SQL.

Verify the provider idempotency key is unchanged, only one external fiscalization exists, the job reaches `SUCCESS`, queue age drains and no new dead letters appear. If duplicate external effects are possible, stop retries and escalate to the provider with the stored provider request ID.
