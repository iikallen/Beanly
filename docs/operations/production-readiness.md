# Production readiness

## Supported topology

`compose.production.yaml` and `compose.staging.yaml` are standalone Compose models. Do not merge them with development `compose.yaml`: only the reverse proxy publishes host ports (`80` and `443`); API, frontend, PostgreSQL, Redis, workers and the OpenTelemetry collector stay on Docker networks.

The reverse proxy terminates TLS and has the fixed edge address `172.28.0.10` in production (`172.29.0.10` in staging). Uvicorn trusts only that address. Certificates are host-managed read-only inputs; this repository does not issue or renew them.

Production and staging must use different projects, databases, Redis credentials, JWT/audit secrets, Fernet keys, provider sandbox credentials and telemetry projects. Never copy `production.env` to staging.

## External prerequisites

Before declaring production ready, operators must provide and independently validate:

- a Linux host with current Docker Engine/Compose, firewall allowing only SSH, TCP 80 and 443;
- DNS and a renewable TLS certificate/key at the configured host paths;
- GHCR images tagged with the exact 40-character Git SHA and registry tag immutability enabled;
- digest-pinned reverse-proxy and OpenTelemetry Collector images;
- an external OTLP backend with alerts configured;
- an encrypted off-host backup target plus working encryption, upload, download and verification hooks;
- managed PostgreSQL PITR or tested WAL archiving with archive-lag alerts;
- a dedicated synthetic smoke-test organization with no customer data.

The checked-in files are executable configuration and validation contracts. They do not prove that DNS, certificates, off-host storage, PITR, registry immutability, telemetry retention or alert delivery exist.

## Resource and connection budgets

Production defaults reserve at most 80 database connections: five database-using processes × (`pool_size=5` + `max_overflow=5`) plus 10 admin connections = 60 steady-state potential connections, leaving 20 for migration/replacement headroom under PostgreSQL's usual 100-connection default. Recalculate before changing Uvicorn workers, worker replicas or pool settings.

Every long-running service has a restart policy, CPU/memory limit and stop grace period. Application, Redis, proxy and collector filesystems are read-only with explicit tmpfs mounts and all Linux capabilities dropped. PostgreSQL keeps its writable data volume and image entrypoint privileges; isolate the host and prefer managed PostgreSQL for real production.

## Availability and alerts

Initial engineering targets, not customer promises:

- availability 99.9%; simple API p95 below 300 ms; payment completion p95 below 750 ms;
- outbox oldest pending below 10 seconds normally; integration dead letters zero;
- RPO at most 5 minutes; RTO at most 60 minutes; verified backup success 100%.

Alert on API/readiness failure, 5xx spikes, PostgreSQL/Redis unavailability, DB pool saturation, blocked/long transactions, outbox age over 30 seconds, any outbox dead letter, integration queue age over 5 minutes, any integration dead letter, failed/late backup, WAL archive lag over 5 minutes and host disk over 80%. Route alerts through the external telemetry provider and test delivery quarterly.

Useful PostgreSQL checks:

```sql
select state, wait_event_type, wait_event, count(*) from pg_stat_activity group by 1,2,3;
select pid, now() - xact_start as age, query from pg_stat_activity where xact_start is not null order by age desc;
select blocked.pid, blocker.pid from pg_stat_activity blocked join pg_locks bl on bl.pid=blocked.pid and not bl.granted join pg_locks kl on kl.locktype=bl.locktype and kl.database is not distinct from bl.database and kl.relation is not distinct from bl.relation and kl.granted join pg_stat_activity blocker on blocker.pid=kl.pid;
```

## Backup and recovery policy

Run `scripts/backup-postgres.sh` daily from a protected scheduler. Its hooks must encrypt before upload, return an off-host locator and verify that exact remote object's SHA-256. Keep at least 35 daily and 12 monthly recovery points unless legal policy requires more.

Logical dumps alone cannot meet the five-minute RPO. Configure managed PITR or PostgreSQL base backups plus continuous WAL archiving; monitor the last successfully archived WAL. Store JWT, integration encryption keys and provider OAuth secrets in a separately recoverable secret system, not inside the database backup.

Run `scripts/restore-drill.sh` monthly against the latest off-host object, then deploy the restored database into an isolated environment and run `scripts/smoke.py`. Record locator, revision, duration and result. The database-only script is not the full DR exercise.

## Release gates

CI runs backend lint/full tests on PostgreSQL, migration upgrade/downgrade/re-upgrade, frontend lint/typecheck/tests/build, both container builds, dependency review and rendered Compose contract checks. Published application images use the exact Git SHA; deployments build nothing from a server working tree.

See [deployment](../runbooks/deployment.md), [rollback](../runbooks/rollback.md), [database restore](../runbooks/database-restore.md) and [load testing](load-testing.md).
