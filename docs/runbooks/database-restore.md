# Database restore

Initial engineering targets are RPO ≤ 5 minutes and RTO ≤ 60 minutes. Logical daily dumps are defense in depth; the RPO requires managed PITR or continuous WAL archiving.

## Choose the recovery point

Record incident start, last known correct transaction/request ID, latest verified dump locator, latest archived WAL and current release/encryption-key versions. Stop writes before restoring. Never restore over the only production database.

For corruption or operator error, restore managed PostgreSQL/PITR to a new instance at the chosen timestamp. For a logical dump, first run the isolated database drill:

```bash
export REMOTE_BACKUP_URI='<off-host-locator>'
export BACKUP_DOWNLOAD_HOOK=/etc/beanly/hooks/download-backup
export BACKUP_DECRYPT_HOOK=/etc/beanly/hooks/decrypt-backup
export EXPECTED_ALEMBIC_REVISION=0019_production_hardening
./scripts/restore-drill.sh
```

The hooks must retrieve and decrypt the exact remote object. The script restores into a disposable digest-pinned PostgreSQL container, checks the Alembic revision and reads core tables, then destroys the container. It does not itself prove application compatibility.

## Full recovery verification

Create an isolated environment pointing at the restored database and separate Redis. Restore the matching JWT/integration Fernet/provider secrets from the separate secret backup. Run `alembic current --check-heads`, database integrity queries, API readiness and `scripts/smoke.py`. Validate a sample encrypted integration credential can be decrypted without printing it.

Switch traffic only after the release SHA, row-count checks, synthetic login/menu/dashboard/analytics and queue metrics pass. Record actual data-loss window and recovery duration. Keep the failed database read-only until the incident review completes.

If keys are unavailable, the database is not fully recoverable: core data may work but integration credentials must be reconnected. Escalate rather than deleting ciphertext or generating replacement keys.
