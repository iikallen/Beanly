import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.modules.integrations.domain.entities import IntegrationJob
from beanly.modules.integrations.domain.enums import (
    IntegrationCapability,
    IntegrationJobStatus,
)
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationInboxEventModel,
    IntegrationJobAttemptModel,
    IntegrationJobModel,
)
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)

INTEGRATION_TABLES = {
    "integration_connections",
    "integration_location_bindings",
    "integration_oauth_sessions",
    "integration_jobs",
    "integration_job_attempts",
    "integration_inbox_events",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _schema(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    return {
        "revision": sync_connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ),
        "tables": tables,
        "columns": {
            table: {column["name"]: column for column in inspector.get_columns(table)}
            for table in INTEGRATION_TABLES
            if table in tables
        },
        "checks": {
            table: {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table)
            }
            for table in INTEGRATION_TABLES
            if table in tables
        },
        "uniques": {
            table: {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table)
            }
            for table in INTEGRATION_TABLES
            if table in tables
        },
        "indexes": {
            table: {
                index["name"]: tuple(index["column_names"])
                for index in inspector.get_indexes(table)
            }
            for table in INTEGRATION_TABLES
            if table in tables
        },
    }


@pytest.mark.anyio
async def test_0018_integrations_upgrade_contract_downgrade_and_reupgrade() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_integrations_migration_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(test_url)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = _config(test_url)
        await asyncio.to_thread(command.upgrade, config, "0018_integrations")
        async with engine.connect() as connection:
            schema = await connection.run_sync(_schema)

        assert schema["revision"] == "0018_integrations"
        assert INTEGRATION_TABLES <= schema["tables"]
        assert schema["uniques"]["integration_location_bindings"] == {
            ("connection_id", "location_id", "capability")
        }
        assert schema["uniques"]["integration_oauth_sessions"] == {
            ("state_hash",)
        }
        assert schema["uniques"]["integration_jobs"] == {
            ("connection_id", "idempotency_key")
        }
        assert schema["uniques"]["integration_job_attempts"] == {
            ("job_id", "attempt_number")
        }
        assert schema["uniques"]["integration_inbox_events"] == {
            ("connection_id", "external_event_id")
        }
        assert {
            "ck_integration_connection_status",
            "ck_integration_connection_auth",
        } <= schema["checks"]["integration_connections"]
        assert {
            "ck_integration_job_capability",
            "ck_integration_job_status",
            "ck_integration_job_attempts",
        } <= schema["checks"]["integration_jobs"]
        assert schema["columns"]["integration_connections"][
            "credentials_ciphertext"
        ]["nullable"]
        assert "credentials" not in schema["columns"]["integration_jobs"]
        assert "payload" not in schema["columns"]["integration_jobs"]
        assert schema["indexes"]["integration_jobs"][
            "ix_integration_jobs_claim"
        ] == ("status", "available_at", "locked_until")

        await asyncio.to_thread(
            command.downgrade, config, "0017_analytics_read_models"
        )
        async with engine.connect() as connection:
            downgraded = await connection.run_sync(_schema)
        assert downgraded["revision"] == "0017_analytics_read_models"
        assert not INTEGRATION_TABLES & downgraded["tables"]

        await asyncio.to_thread(command.upgrade, config, "0018_integrations")
        async with engine.connect() as connection:
            reupgraded = await connection.run_sync(_schema)
        assert reupgraded["revision"] == "0018_integrations"
        assert INTEGRATION_TABLES <= reupgraded["tables"]

        user_id = uuid4()
        organization_id = uuid4()
        location_id = uuid4()
        connection_id = uuid4()
        job_id = uuid4()
        now = datetime(2026, 8, 10, 12, tzinfo=UTC)
        idempotency_key = f"fiscalize:payment:{uuid4()}"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,email,password_hash,first_name,last_name) "
                    "VALUES (:id,:email,'unused','Integration','Owner')"
                ),
                {"id": user_id, "email": f"integration-{user_id}@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id,name,country_code,currency_code,created_by) "
                    "VALUES (:id,'Integration','KZ','KZT',:user_id)"
                ),
                {"id": organization_id, "user_id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO locations "
                    "(id,organization_id,name,timezone,is_active,is_primary) "
                    "VALUES (:id,:organization_id,'Dostyk','Asia/Almaty',true,true)"
                ),
                {"id": location_id, "organization_id": organization_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO integration_connections "
                    "(id,organization_id,provider_code,display_name,status,auth_type,"
                    "config,credentials_ciphertext,credentials_key_version,created_by,"
                    "created_at,updated_at) VALUES "
                    "(:id,:organization_id,'mock_fiscal','Mock','ACTIVE','API_KEY',"
                    "'{}'::json,NULL,NULL,:user_id,:now,:now)"
                ),
                {
                    "id": connection_id,
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO integration_jobs "
                    "(id,organization_id,connection_id,location_id,capability,job_type,"
                    "source_type,source_id,idempotency_key,status,available_at,attempts,"
                    "created_at,updated_at) VALUES "
                    "(:id,:organization_id,:connection_id,:location_id,'FISCAL',"
                    "'FISCALIZE_PAYMENT','PAYMENT',:source_id,:idempotency_key,'PENDING',"
                    ":now,0,:now,:now)"
                ),
                {
                    "id": job_id,
                    "organization_id": organization_id,
                    "connection_id": connection_id,
                    "location_id": location_id,
                    "source_id": uuid4(),
                    "idempotency_key": idempotency_key,
                    "now": now,
                },
            )

        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def claim(worker_id: str, claimed_at: datetime) -> list:
            async with sessions() as session:
                result = await SqlAlchemyIntegrationRepository(session).claim_jobs(
                    worker_id, 10, 1, claimed_at
                )
                await session.commit()
                return result

        first_claims = await asyncio.gather(
            claim("integration-worker-a", now),
            claim("integration-worker-b", now),
        )
        assert sorted(len(value) for value in first_claims) == [0, 1]
        first_worker = (
            "integration-worker-a" if first_claims[0] else "integration-worker-b"
        )
        expired_at = now + timedelta(seconds=2)
        async with sessions() as session:
            repository = SqlAlchemyIntegrationRepository(session)
            with pytest.raises(RuntimeError, match="lease lost"):
                await repository.mark_job_succeeded(
                    job_id,
                    first_worker,
                    external_id="must-not-win",
                    provider_request_id=None,
                    started_at=now,
                    duration_ms=2_000,
                    now=expired_at,
                )
            await session.rollback()

        recovered = await claim("integration-worker-recovery", expired_at)
        assert [value.id for value in recovered] == [job_id]
        async with sessions() as session:
            repository = SqlAlchemyIntegrationRepository(session)
            await repository.mark_job_failed(
                job_id,
                "integration-worker-recovery",
                TimeoutError("provider unavailable api_key=must-not-persist"),
                2,
                temporary=True,
                started_at=expired_at,
                duration_ms=25,
                now=expired_at,
            )
            await session.commit()

        async with sessions() as session:
            retrying = await session.get(IntegrationJobModel, job_id)
            assert retrying is not None
            assert retrying.status == "RETRYING"
            assert retrying.attempts == 1
            assert retrying.available_at > expired_at
            assert retrying.last_error_message == "Provider request failed"
            assert "must-not-persist" not in repr(retrying)
            retry_at = retrying.available_at + timedelta(seconds=1)

        assert [value.id for value in await claim("integration-worker-final", retry_at)] == [
            job_id
        ]
        async with sessions() as session:
            repository = SqlAlchemyIntegrationRepository(session)
            await repository.mark_job_failed(
                job_id,
                "integration-worker-final",
                ValueError("invalid provider request"),
                2,
                temporary=False,
                started_at=retry_at,
                duration_ms=10,
                now=retry_at,
            )
            await session.commit()

        async with sessions() as session:
            dead = await session.get(IntegrationJobModel, job_id)
            assert dead is not None
            assert dead.status == "DEAD"
            assert dead.attempts == 2
            assert dead.dead_lettered_at == retry_at
            assert await session.scalar(
                select(func.count(IntegrationJobAttemptModel.id)).where(
                    IntegrationJobAttemptModel.job_id == job_id
                )
            ) == 2
            repository = SqlAlchemyIntegrationRepository(session)
            retried = await repository.retry_job(organization_id, job_id)
            await session.commit()
            assert retried.status.value == "RETRYING"
            assert retried.idempotency_key == idempotency_key
            assert retried.dead_lettered_at is None

        duplicate_key = f"fiscalize:payment:{uuid4()}"
        duplicate_source = uuid4()

        async def add_duplicate_job():
            timestamp = datetime.now(UTC)
            async with sessions() as session:
                repository = SqlAlchemyIntegrationRepository(session)
                result = await repository.add_job(
                    IntegrationJob(
                        id=uuid4(),
                        organization_id=organization_id,
                        connection_id=connection_id,
                        location_id=location_id,
                        capability=IntegrationCapability.FISCAL,
                        job_type="FISCALIZE_PAYMENT",
                        source_event_id=uuid4(),
                        source_type="PAYMENT",
                        source_id=duplicate_source,
                        idempotency_key=duplicate_key,
                        status=IntegrationJobStatus.PENDING,
                        available_at=timestamp,
                        attempts=0,
                        locked_by=None,
                        locked_until=None,
                        external_id=None,
                        completed_at=None,
                        dead_lettered_at=None,
                        last_error_code=None,
                        last_error_message=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                await repository.commit()
                return result.id

        duplicate_results = await asyncio.gather(
            add_duplicate_job(), add_duplicate_job()
        )
        assert duplicate_results[0] == duplicate_results[1]
        async with sessions() as session:
            assert await session.scalar(
                select(func.count(IntegrationJobModel.id)).where(
                    IntegrationJobModel.connection_id == connection_id,
                    IntegrationJobModel.idempotency_key == duplicate_key,
                )
            ) == 1

        inbox_id = uuid4()
        inbox_now = datetime(2026, 8, 10, 14, tzinfo=UTC)
        async with sessions() as session:
            session.add(
                IntegrationInboxEventModel(
                    id=inbox_id,
                    organization_id=organization_id,
                    connection_id=connection_id,
                    provider_code="mock_fiscal",
                    external_event_id="evt-concurrency",
                    event_type="receipt.ready",
                    payload={"status": "ready"},
                    payload_hash="0" * 64,
                    received_at=inbox_now,
                    processed_at=None,
                    attempts=0,
                    available_at=inbox_now,
                    locked_by=None,
                    locked_until=None,
                    dead_lettered_at=None,
                    last_error=None,
                )
            )
            await session.commit()

        async def claim_inbox(worker_id: str, claimed_at: datetime):
            async with sessions() as session:
                result = await SqlAlchemyIntegrationRepository(session).claim_inbox(
                    worker_id, 10, 1, claimed_at
                )
                await session.commit()
                return result

        inbox_claims = await asyncio.gather(
            claim_inbox("inbox-worker-a", inbox_now),
            claim_inbox("inbox-worker-b", inbox_now),
        )
        assert sorted(len(value) for value in inbox_claims) == [0, 1]
        first_inbox_worker = "inbox-worker-a" if inbox_claims[0] else "inbox-worker-b"
        inbox_expired_at = inbox_now + timedelta(seconds=2)
        async with sessions() as session:
            repository = SqlAlchemyIntegrationRepository(session)
            with pytest.raises(RuntimeError, match="lease lost"):
                await repository.mark_inbox_processed(
                    inbox_id, first_inbox_worker, inbox_expired_at
                )
            await session.rollback()

        assert await claim_inbox("inbox-worker-recovery", inbox_expired_at) == [
            inbox_id
        ]
        async with sessions() as session:
            repository = SqlAlchemyIntegrationRepository(session)
            await repository.mark_inbox_failed(
                inbox_id,
                "inbox-worker-recovery",
                RuntimeError("refresh_token=must-not-persist"),
                2,
                inbox_expired_at,
            )
            await repository.commit()

        async with sessions() as session:
            retrying_inbox = await session.get(IntegrationInboxEventModel, inbox_id)
            assert retrying_inbox is not None
            assert retrying_inbox.attempts == 1
            assert retrying_inbox.last_error == "RuntimeError: Inbox processing failed"
            assert "must-not-persist" not in retrying_inbox.last_error
            inbox_retry_at = retrying_inbox.available_at + timedelta(seconds=1)

        assert await claim_inbox("inbox-worker-final", inbox_retry_at) == [inbox_id]
        async with sessions() as session:
            repository = SqlAlchemyIntegrationRepository(session)
            assert await repository.mark_inbox_processed(
                inbox_id, "inbox-worker-final", inbox_retry_at
            ) == organization_id
            await repository.commit()
            processed_inbox = await session.get(IntegrationInboxEventModel, inbox_id)
            assert processed_inbox is not None
            assert processed_inbox.processed_at == inbox_retry_at
            assert processed_inbox.attempts == 2
            assert processed_inbox.dead_lettered_at is None
    finally:
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}"')
            )
        await admin_engine.dispose()
