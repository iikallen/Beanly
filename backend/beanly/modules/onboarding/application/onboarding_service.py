from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.observability import metrics
from beanly.modules.onboarding.application.ports import OnboardingGateway, OnboardingRepository
from beanly.modules.onboarding.domain.entities import OnboardingState
from beanly.modules.onboarding.domain.enums import OnboardingStatus
from beanly.modules.organizations.domain.entities import TenantContext


class OnboardingService:
    def __init__(self, repository: OnboardingRepository, gateway: OnboardingGateway) -> None:
        self.repository = repository
        self.gateway = gateway

    async def status(self, context: TenantContext) -> dict[str, object]:
        state = await self.repository.get_state(context.organization_id)
        readiness = await self.gateway.readiness(context)
        if state is None and readiness["pos_ready"]:
            origin = await self.gateway.organization_origin(context.organization_id)
            if origin is not None:
                creator, started_at = origin
                now = datetime.now(UTC)
                state = OnboardingState(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    status=OnboardingStatus.READY_FOR_POS,
                    current_step="pos",
                    started_at=started_at,
                    completed_at=None,
                    dismissed_at=None,
                    created_by=creator,
                    updated_at=now,
                )
                try:
                    await self.repository.add_state(state)
                    await self.repository.commit()
                except Exception:
                    await self.repository.rollback()
                    state = await self.repository.get_state(context.organization_id)
                    if state is None:
                        raise
                else:
                    metrics.onboarding_time_to_pos_ready.record(
                        _elapsed_seconds(started_at, now)
                    )
        if (
            state is not None
            and state.status not in {OnboardingStatus.READY_FOR_POS, OnboardingStatus.COMPLETED}
            and readiness["pos_ready"]
        ):
            now = datetime.now(UTC)
            try:
                state = await self.repository.get_state(context.organization_id, lock=True)
                if state is not None and state.status not in {
                    OnboardingStatus.READY_FOR_POS,
                    OnboardingStatus.COMPLETED,
                }:
                    state.status = OnboardingStatus.READY_FOR_POS
                    state.current_step = "pos"
                    state.updated_at = now
                    await self.repository.save_state(state)
                    await self.repository.commit()
                    metrics.onboarding_time_to_pos_ready.record(
                        _elapsed_seconds(state.started_at, now)
                    )
            except Exception:
                await self.repository.rollback()
                raise
        effective = (
            state.status
            if state
            else OnboardingStatus.READY_FOR_POS
            if readiness["pos_ready"]
            else OnboardingStatus.NOT_STARTED
        )
        return {
            "status": effective,
            "current_step": state.current_step if state else "workspace",
            "steps": readiness["steps"],
            "pos_ready": readiness["pos_ready"],
            "ai_available": False,
            "started_at": state.started_at if state else None,
            "completed_at": state.completed_at if state else None,
            "dismissed_at": state.dismissed_at if state else None,
        }

    async def bootstrap(
        self, context: TenantContext, warehouse_name: str, register_name: str
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        try:
            result = await self.gateway.bootstrap(context, warehouse_name, register_name, now)
            state = await self.repository.get_state(context.organization_id, lock=True)
            if state is None:
                state = OnboardingState(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    status=OnboardingStatus.IN_PROGRESS,
                    current_step="menu",
                    started_at=now,
                    completed_at=None,
                    dismissed_at=None,
                    created_by=context.user_id,
                    updated_at=now,
                )
                await self.repository.add_state(state)
                metrics.onboarding_started.add(1)
            else:
                state.current_step = "menu"
                state.updated_at = now
                await self.repository.save_state(state)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return {
            "location_id": result.location_id,
            "warehouse_id": result.warehouse_id,
            "register_id": result.register_id,
            "created": {
                "warehouse": result.warehouse_created,
                "register": result.register_created,
            },
            "onboarding": await self.status(context),
        }

    async def dismiss(self, context: TenantContext) -> dict[str, object]:
        now = datetime.now(UTC)
        try:
            state = await self.repository.get_state(context.organization_id, lock=True)
            if state is None:
                state = OnboardingState(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    status=OnboardingStatus.NOT_STARTED,
                    current_step=None,
                    started_at=now,
                    completed_at=None,
                    dismissed_at=now,
                    created_by=context.user_id,
                    updated_at=now,
                )
                await self.repository.add_state(state)
            else:
                state.dismissed_at = now
                state.updated_at = now
                await self.repository.save_state(state)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.status(context)

    async def complete_from_payment(self, organization_id: UUID, occurred_at: datetime) -> bool:
        state = await self.repository.get_state(organization_id, lock=True)
        if state is not None and state.completed_at is not None:
            return False
        pos_ready_metric_required = (
            state is None or state.status is not OnboardingStatus.READY_FOR_POS
        )
        if state is None:
            origin = await self.gateway.organization_origin(organization_id)
            if origin is None:
                return False
            creator, organization_created_at = origin
            state = OnboardingState(
                id=uuid4(),
                organization_id=organization_id,
                status=OnboardingStatus.COMPLETED,
                current_step="completed",
                started_at=organization_created_at,
                completed_at=occurred_at,
                dismissed_at=None,
                created_by=creator,
                updated_at=occurred_at,
            )
            await self.repository.add_state(state)
        else:
            state.status = OnboardingStatus.COMPLETED
            state.current_step = "completed"
            state.completed_at = occurred_at
            state.updated_at = occurred_at
            await self.repository.save_state(state)
        metrics.onboarding_completed.add(1)
        if pos_ready_metric_required:
            metrics.onboarding_time_to_pos_ready.record(
                _elapsed_seconds(state.started_at, occurred_at)
            )
        metrics.onboarding_time_to_first_sale.record(
            _elapsed_seconds(state.started_at, occurred_at)
        )
        return True


def _elapsed_seconds(started_at: datetime, ended_at: datetime) -> float:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=UTC)
    return max(0.0, (ended_at - started_at).total_seconds())
