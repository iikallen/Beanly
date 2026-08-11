from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.refunds.application.dto import RefundInput, RefundPreview
from beanly.modules.refunds.domain.entities import Refund


@dataclass(frozen=True, slots=True)
class ReturnStockLine:
    inventory_item_id: UUID
    base_unit: str
    quantity: Decimal
    original_unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class RefundPlan:
    preview: RefundPreview
    location_id: UUID
    warehouse_id: UUID
    currency_code: str
    cogs_quality_status: str
    stock_lines: tuple[ReturnStockLine, ...]


class RefundInventoryPort(Protocol):
    async def stage_return(
        self,
        context: TenantContext,
        refund_id: UUID,
        warehouse_id: UUID,
        lines: tuple[ReturnStockLine, ...],
    ) -> tuple[UUID | None, Decimal, tuple[object, ...]]: ...


class RefundSourcePort(Protocol):
    async def payment_location(
        self, organization_id: UUID, payment_id: UUID
    ) -> UUID | None: ...

    async def lock_payment(self, organization_id: UUID, payment_id: UUID) -> UUID: ...

    async def plan(
        self,
        organization_id: UUID,
        value: RefundInput,
        *,
        lock: bool,
        require_external_confirmation: bool,
    ) -> RefundPlan: ...


class RefundAccessPort(Protocol):
    async def ensure_location(self, context: TenantContext, location_id: UUID) -> None: ...
    async def location_ids(self, context: TenantContext) -> tuple[UUID, ...]: ...


class RefundStorePort(Protocol):
    async def get(self, organization_id: UUID, refund_id: UUID) -> Refund | None: ...
    async def get_by_client_id(
        self, organization_id: UUID, client_refund_id: UUID
    ) -> Refund | None: ...
    async def add(self, value: Refund) -> Refund: ...
    async def list(
        self,
        organization_id: UUID,
        *,
        location_ids: tuple[UUID, ...],
        location_id: UUID | None,
        order_id: UUID | None,
        payment_id: UUID | None,
        status: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[Refund]: ...
    async def fiscal_status(
        self, organization_id: UUID, refund_id: UUID
    ) -> tuple[str, str | None, str | None]: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
