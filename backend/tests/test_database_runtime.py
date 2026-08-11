from types import SimpleNamespace

import pytest

from beanly.core.config.settings import Settings
from beanly.core.database import session as database_session
from beanly.core.observability.telemetry import _otlp_is_insecure


@pytest.mark.parametrize(
    ("service_name", "expected_statement_timeout"),
    [("beanly-api", "11000"), ("beanly-integration-worker", "70000")],
)
def test_engine_factory_applies_pool_and_postgres_session_limits(
    monkeypatch, service_name: str, expected_statement_timeout: str
) -> None:
    captured: dict[str, object] = {}
    sentinel = SimpleNamespace()

    def capture(url: str, **options: object) -> object:
        captured.update(url=url, **options)
        return sentinel

    monkeypatch.setattr(database_session, "create_async_engine", capture)
    monkeypatch.setattr(database_session, "_instrument_pool", lambda _engine: None)
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://beanly:secret@postgres:5432/beanly",
        service_name=service_name,
        db_pool_size=7,
        db_max_overflow=3,
        db_pool_timeout_seconds=4,
        db_pool_recycle_seconds=900,
        db_statement_timeout_ms=11_000,
        db_worker_statement_timeout_ms=70_000,
    )

    assert database_session.build_engine(settings) is sentinel
    assert captured == {
        "url": settings.database_url,
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 3,
        "pool_timeout": 4,
        "pool_recycle": 900,
        "connect_args": {
            "server_settings": {
                "application_name": service_name,
                "statement_timeout": expected_statement_timeout,
                "lock_timeout": "3000",
            }
        },
    }


class _Session:
    def __init__(self, dialect: str) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class _SessionContext:
    def __init__(self) -> None:
        self.connection_requested = False

    async def __aenter__(self) -> "_SessionContext":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def connection(self) -> object:
        self.connection_requested = True
        return object()


@pytest.mark.anyio
async def test_transaction_timeout_override_is_postgres_only() -> None:
    postgres = _Session("postgresql")
    sqlite = _Session("sqlite")

    await database_session.apply_transaction_timeouts(
        postgres,  # type: ignore[arg-type]
        statement_timeout_ms=120_000,
        lock_timeout_ms=15_000,
    )
    await database_session.apply_transaction_timeouts(
        sqlite,  # type: ignore[arg-type]
        statement_timeout_ms=120_000,
        lock_timeout_ms=15_000,
    )

    assert postgres.statements == [
        "SET LOCAL statement_timeout = 120000",
        "SET LOCAL lock_timeout = 15000",
    ]
    assert sqlite.statements == []


def test_otlp_transport_only_uses_plaintext_for_explicit_http() -> None:
    assert _otlp_is_insecure("http://otel-collector:4317") is True
    assert _otlp_is_insecure("https://otel.example.com:4317") is False
    assert _otlp_is_insecure(None) is False


@pytest.mark.anyio
async def test_request_session_records_real_pool_acquisition_wait(monkeypatch) -> None:
    context = _SessionContext()
    recorded: list[float] = []
    times = iter((10.0, 10.025))
    monkeypatch.setattr(database_session, "session_factory", lambda: context)
    monkeypatch.setattr(database_session.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(
        database_session.metrics.db_pool_wait,
        "record",
        lambda value: recorded.append(value),
    )

    yielded = [session async for session in database_session.get_session()]

    assert yielded == [context]
    assert context.connection_requested is True
    assert recorded == pytest.approx([25.0])
