from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.domain.enums import OrderStatus, SaleCostStatus


@dataclass(frozen=True, slots=True)
class SaleComponentSnapshot:
    inventory_item_id: UUID
    base_unit: UnitCode
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class SaleStockLine:
    inventory_item_id: UUID
    base_unit: UnitCode
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class StagedSaleResult:
    inventory_transaction_id: UUID | None
    cogs_amount: Decimal
    cogs_status: SaleCostStatus
    missing_cost_item_ids: tuple[UUID, ...]
    events: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class PayableOrderSnapshot:
    id: UUID
    organization_id: UUID
    location_id: UUID
    shift_id: UUID
    warehouse_id: UUID
    status: OrderStatus
    currency_code: str
    total_minor: int
    created_by_user_id: UUID | None
    has_items: bool
    shift_is_open: bool
    order_number: int
    sale_components: tuple[SaleComponentSnapshot, ...]
    pricing_revision: int = 1


class SalesSettlementPort(Protocol):
    async def lock_order_for_payment(
        self, context: TenantContext, order_id: UUID
    ) -> PayableOrderSnapshot: ...

    async def mark_order_paid(
        self,
        order_id: UUID,
        paid_by_user_id: UUID,
        paid_at: datetime,
        inventory_transaction_id: UUID | None,
        cogs_amount: Decimal,
        cogs_status: SaleCostStatus,
    ) -> None: ...

    async def stage_loyalty_payment(
        self,
        payment_id: UUID,
        organization_id: UUID,
        order_id: UUID,
        amount_minor: int,
        paid_at: datetime,
    ) -> None: ...

    async def ensure_location_access(self, context: TenantContext, location_id: UUID) -> None: ...

    async def accessible_location_ids(self, context: TenantContext) -> tuple[UUID, ...]: ...

    async def ensure_shift_access(self, context: TenantContext, shift_id: UUID) -> None: ...


class InventorySalePort(Protocol):
    async def stage_sale(
        self,
        context: TenantContext,
        *,
        order_id: UUID,
        order_number: int,
        warehouse_id: UUID,
        lines: tuple[SaleStockLine, ...],
        occurred_at: datetime | None = None,
    ) -> StagedSaleResult: ...


class FiscalSnapshotPort(Protocol):
    async def stage_payment_snapshot(self, organization_id: UUID, payment_id: UUID) -> None: ...


class FiscalCheckoutPort(Protocol):
    async def preflight(
        self, context: TenantContext, *, order_id: UUID, location_id: UUID
    ) -> None: ...
