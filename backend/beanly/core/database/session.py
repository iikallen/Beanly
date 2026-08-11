import time
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from beanly.core.config.settings import Settings, get_settings
from beanly.core.observability.metrics import metrics

settings = get_settings()


def build_engine(settings: Settings) -> AsyncEngine:
    options: dict[str, object] = {"pool_pre_ping": True}
    if not settings.database_url.startswith("sqlite"):
        statement_timeout = (
            settings.db_worker_statement_timeout_ms
            if "worker" in settings.service_name
            else settings.db_statement_timeout_ms
        )
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
            connect_args={
                "server_settings": {
                    "application_name": settings.service_name,
                    "statement_timeout": str(statement_timeout),
                    "lock_timeout": str(settings.db_lock_timeout_ms),
                }
            },
        )
    value = create_async_engine(settings.database_url, **options)
    _instrument_pool(value)
    return value


def _instrument_pool(value: AsyncEngine) -> None:
    pool = value.sync_engine.pool

    def update_pool(*_: object) -> None:
        size = getattr(pool, "size", lambda: 0)()
        checked_out = getattr(pool, "checkedout", lambda: 0)()
        metrics.set_db_pool(connections=size, checked_out=checked_out)

    event.listen(pool, "connect", update_pool)
    event.listen(pool, "close", update_pool)
    event.listen(pool, "checkout", update_pool)
    event.listen(pool, "checkin", update_pool)
    event.listen(
        value.sync_engine,
        "handle_error",
        lambda *_: metrics.db_errors.add(1),
    )


engine = build_engine(settings)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        started = time.perf_counter()
        await session.connection()
        metrics.db_pool_wait.record(max(0, (time.perf_counter() - started) * 1000))
        yield session


async def apply_transaction_timeouts(
    session: AsyncSession,
    *,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> None:
    """Override defaults for one PostgreSQL transaction (analytics/backfills)."""
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    await session.execute(text(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}"))
    await session.execute(text(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}"))
