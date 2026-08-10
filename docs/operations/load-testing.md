# Load testing

Use staging with production-like resources and synthetic data. Never run load or write-concurrency tests against customer organizations.

The dependency-free read probe exercises HTTPS and accepts repeatable paths:

```bash
export LOAD_ACCESS_TOKEN='synthetic-token'
export LOAD_ORGANIZATION_ID='synthetic-org-uuid'
python3 scripts/load_read_paths.py https://staging.beanly.example.com \
  --requests 1000 --concurrency 50 --max-p95-ms 300 \
  --path '/api/v1/menu?location_id=synthetic-location-uuid' \
  --path '/api/v1/dashboard/overview?period=today' \
  --path '/api/v1/analytics/overview?date_from=2026-08-01&date_to=2026-08-10'
```

Record release SHA, dataset size, concurrency, throughput, p50/p95/p99, errors, CPU/memory, DB connections/lock waits and queue ages.

Payment/inventory tests must use the existing API idempotency keys and assert database invariants, not just HTTP status:

- 100 simultaneous payments for different orders sharing inventory: one payment and one SALE ledger entry per order, exact stock balance;
- multiple requests for the same order and `client_payment_id`: exactly one payment and one SALE result;
- 10,000 outbox events: queue drains, dead letters remain zero and DB pool stays within budget;
- 1,000 MockFiscal jobs with 5% temporary failures: retries occur, provider idempotency keys stay stable and fiscalization is not duplicated.

These write scenarios belong in isolated PostgreSQL integration tests/load fixtures. The checked-in read probe intentionally cannot create sales.
