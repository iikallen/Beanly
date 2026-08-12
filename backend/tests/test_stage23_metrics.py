from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.onboarding.application.onboarding_service import OnboardingService
from beanly.modules.onboarding.domain.entities import OnboardingState
from beanly.modules.onboarding.domain.enums import OnboardingStatus
from beanly.modules.onboarding.infrastructure.handlers import register_onboarding_handlers


class _InstrumentSpy:
    def __init__(self) -> None:
        self.values: list[float] = []

    def add(self, value: float) -> None:
        self.values.append(value)

    def record(self, value: float) -> None:
        self.values.append(value)


class _Repository:
    def __init__(self, state: OnboardingState) -> None:
        self.state = state
        self.saved = 0
        self.commits = 0
        self.rollbacks = 0
        self.trace: list[str] = []

    async def get_state(self, organization_id: UUID, *, lock: bool = False):
        assert organization_id == self.state.organization_id
        if lock:
            self.trace.append("state_locked")
        return self.state

    async def add_state(self, state: OnboardingState) -> None:
        self.state = state
        self.trace.append("state_added")

    async def save_state(self, state: OnboardingState) -> None:
        self.state = state
        self.saved += 1
        self.trace.append("state_saved")

    async def commit(self) -> None:
        self.commits += 1
        self.trace.append("committed")

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Gateway:
    def __init__(self, *, pos_ready: bool) -> None:
        self.pos_ready = pos_ready

    async def readiness(self, _context):
        return {"steps": {}, "pos_ready": self.pos_ready}

    async def organization_origin(self, _organization_id):
        return None


class _AuditSpy:
    def __init__(self, trace: list[str]) -> None:
        self.calls: list[dict[str, object]] = []
        self.trace = trace

    async def record(self, **values):
        self.trace.append("audit_recorded")
        self.calls.append(values)


def _state(now: datetime) -> OnboardingState:
    return OnboardingState(
        id=uuid4(),
        organization_id=uuid4(),
        status=OnboardingStatus.IN_PROGRESS,
        current_step="menu",
        started_at=now - timedelta(minutes=12),
        completed_at=None,
        dismissed_at=None,
        created_by=uuid4(),
        updated_at=now - timedelta(minutes=12),
    )


@pytest.mark.anyio
async def test_pos_ready_transition_is_persisted_and_measured_exactly_once(monkeypatch) -> None:
    now = datetime.now(UTC)
    repository = _Repository(_state(now))
    histogram = _InstrumentSpy()
    monkeypatch.setattr(
        "beanly.modules.onboarding.application.onboarding_service.metrics.onboarding_time_to_pos_ready",
        histogram,
    )
    service = OnboardingService(repository, _Gateway(pos_ready=True))
    context = SimpleNamespace(organization_id=repository.state.organization_id)

    first = await service.status(context)
    second = await service.status(context)

    assert first["status"] is second["status"] is OnboardingStatus.READY_FOR_POS
    assert repository.state.status is OnboardingStatus.READY_FOR_POS
    assert repository.saved == repository.commits == 1
    assert len(histogram.values) == 1
    assert histogram.values[0] >= 12 * 60


@pytest.mark.anyio
async def test_duplicate_payment_event_records_completion_metric_and_audit_once(
    monkeypatch,
) -> None:
    occurred_at = datetime.now(UTC)
    repository = _Repository(_state(occurred_at))
    completed = _InstrumentSpy()
    first_sale = _InstrumentSpy()
    pos_ready = _InstrumentSpy()
    monkeypatch.setattr(
        "beanly.modules.onboarding.application.onboarding_service.metrics.onboarding_completed",
        completed,
    )
    monkeypatch.setattr(
        "beanly.modules.onboarding.application.onboarding_service.metrics.onboarding_time_to_first_sale",
        first_sale,
    )
    monkeypatch.setattr(
        "beanly.modules.onboarding.application.onboarding_service.metrics.onboarding_time_to_pos_ready",
        pos_ready,
    )
    service = OnboardingService(repository, _Gateway(pos_ready=False))
    audit = _AuditSpy(repository.trace)
    registry = EventHandlerRegistry()
    register_onboarding_handlers(registry, service, audit)
    envelope = EventEnvelope(
        id=uuid4(),
        organization_id=repository.state.organization_id,
        event_name="payment.completed",
        event_version=1,
        aggregate_type="payment",
        aggregate_id=uuid4(),
        payload={},
        occurred_at=occurred_at,
    )

    await registry.dispatch(envelope)
    await registry.dispatch(envelope)

    assert repository.state.status is OnboardingStatus.COMPLETED
    assert repository.state.completed_at == occurred_at
    assert completed.values == [1]
    assert len(first_sale.values) == 1
    assert len(pos_ready.values) == 1
    assert len(audit.calls) == 1
    assert audit.calls[0]["action"] == "ONBOARDING_COMPLETED"
    assert audit.calls[0]["metadata"] == {"source_event_id": str(envelope.id)}
    assert repository.trace[:3] == ["state_locked", "state_saved", "audit_recorded"]
    assert repository.commits == repository.rollbacks == 0
