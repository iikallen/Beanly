# Integration provider outage

Core sales and payments remain authoritative. A provider outage must not cause operators to recreate payments or mutate integration jobs directly.

Confirm the provider and affected capabilities from health checks, integration job error codes, retry counts, oldest pending age, and dead-letter totals. Pause manual retries while the provider is unavailable. Preserve the original job and provider idempotency keys.

For fiscal providers, follow the applicable legal fallback procedure and record the incident window. For delivery or notification providers, communicate delayed external processing without claiming the core transaction failed. After recovery, allow automatic retries to drain, then retry DEAD jobs through the Owner/Admin API. Verify one external effect per stable idempotency key and monitor queue age until normal.
