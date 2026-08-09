import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.application.ports import (
    NullSalesEventPublisher,
    SalesEventPublisher,
)
from beanly.modules.sales.domain.entities import PosRegister
from beanly.modules.sales.domain.events import PosRegisterCreated
from beanly.modules.sales.domain.exceptions import (
    InvalidSalesOperation,
    SalesNotFound,
)
from beanly.modules.sales.domain.repositories import SalesRepository

logger = logging.getLogger(__name__)


class RegisterService:
    def __init__(
        self,
        repository: SalesRepository,
        organizations: OrganizationService,
        publisher: SalesEventPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.publisher = publisher or NullSalesEventPublisher()

    async def create(
        self, context: TenantContext, location_id: UUID, name: str
    ) -> PosRegister:
        await self.organizations.ensure_location_access(context, location_id)
        now = datetime.now(UTC)
        value = PosRegister(
            uuid4(),
            context.organization_id,
            location_id,
            _name(name),
            True,
            context.user_id,
            now,
            now,
        )
        return await self._write(
            self.repository.add_register(value), (PosRegisterCreated(value.id),)
        )

    async def list(
        self, context: TenantContext, location_id: UUID | None
    ) -> list[PosRegister]:
        if location_id is not None:
            await self.organizations.ensure_location_access(context, location_id)
            return await self.repository.list_registers(context.organization_id, location_id)
        locations = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        allowed = {value.id for value in locations}
        values = await self.repository.list_registers(context.organization_id, None)
        return [value for value in values if value.location_id in allowed]

    async def update(
        self, context: TenantContext, register_id: UUID, name: str
    ) -> PosRegister:
        value = await self._register(context, register_id)
        if not value.is_active:
            raise InvalidSalesOperation("Inactive registers cannot be updated")
        return await self._write(
            self.repository.update_register(
                replace(value, name=_name(name), updated_at=datetime.now(UTC))
            )
        )

    async def deactivate(
        self, context: TenantContext, register_id: UUID
    ) -> PosRegister:
        value = await self._register(context, register_id)
        if not value.is_active:
            raise InvalidSalesOperation("Register is already inactive")
        if await self.repository.get_current_shift(context.organization_id, register_id):
            raise InvalidSalesOperation("Register with an OPEN shift cannot be deactivated")
        return await self._write(
            self.repository.update_register(
                replace(value, is_active=False, updated_at=datetime.now(UTC))
            )
        )

    async def _register(
        self, context: TenantContext, register_id: UUID
    ) -> PosRegister:
        value = await self.repository.get_register(context.organization_id, register_id)
        if value is None:
            raise SalesNotFound("Register not found")
        await self.organizations.ensure_location_access(context, value.location_id)
        return value

    async def _write(self, operation, events: tuple[object, ...] = ()):
        try:
            result = await operation
            await self.repository.commit()
            for event in events:
                try:
                    await self.publisher.publish(event)
                except Exception:
                    logger.exception("Sales event publish failed")
            return result
        except Exception:
            await self.repository.rollback()
            raise


def _name(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 150:
        raise ValueError("Name must contain between 1 and 150 characters")
    return normalized
