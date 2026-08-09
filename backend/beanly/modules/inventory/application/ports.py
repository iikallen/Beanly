from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.inventory.domain.entities import (
    InventoryItem,
    InventoryTransaction,
    InventoryTransactionLine,
    MovementRow,
    StockBalance,
    StockRow,
    TransactionDetail,
    Warehouse,
)
from beanly.modules.inventory.domain.enums import InventoryTransactionStatus


class InventoryRepository(Protocol):
    async def add_warehouse(self, warehouse: Warehouse) -> Warehouse: ...
    async def list_warehouses(self, organization_id: UUID) -> list[Warehouse]: ...
    async def get_warehouse(
        self, organization_id: UUID, warehouse_id: UUID
    ) -> Warehouse | None: ...
    async def add_item(self, item: InventoryItem) -> InventoryItem: ...
    async def list_items(self, organization_id: UUID) -> list[InventoryItem]: ...
    async def get_item(
        self,
        organization_id: UUID,
        item_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> InventoryItem | None: ...
    async def get_items_by_ids(
        self, organization_id: UUID, item_ids: tuple[UUID, ...]
    ) -> list[InventoryItem]: ...
    async def get_current_costs(
        self, organization_id: UUID, warehouse_id: UUID, item_ids: tuple[UUID, ...]
    ) -> dict[UUID, Decimal]: ...
    async def add_transaction(self, transaction: InventoryTransaction) -> InventoryTransaction: ...
    async def add_lines(self, lines: tuple[InventoryTransactionLine, ...]) -> None: ...
    async def get_transaction(
        self, organization_id: UUID, transaction_id: UUID, *, lock: bool = False
    ) -> InventoryTransaction | None: ...
    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str
    ) -> TransactionDetail | None: ...
    async def get_reversal(
        self, organization_id: UUID, original_id: UUID
    ) -> TransactionDetail | None: ...
    async def get_lines(
        self, organization_id: UUID, transaction_id: UUID
    ) -> tuple[InventoryTransactionLine, ...]: ...
    async def mark_status(
        self,
        organization_id: UUID,
        transaction_id: UUID,
        status: InventoryTransactionStatus,
        posted_at: datetime | None,
    ) -> None: ...
    async def lock_balances(
        self,
        organization_id: UUID,
        location_id: UUID,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
        now: datetime,
    ) -> dict[UUID, StockBalance]: ...
    async def update_balance(
        self,
        organization_id: UUID,
        balance_id: UUID,
        quantity: Decimal,
        average_unit_cost: Decimal,
        now: datetime,
    ) -> None: ...
    async def update_line_snapshot(
        self,
        organization_id: UUID,
        line_id: UUID,
        unit_cost_amount: Decimal,
        total_cost_amount: Decimal,
        quantity_after: Decimal,
        average_unit_cost_after: Decimal,
    ) -> None: ...
    async def list_stock(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        warehouse_id: UUID | None,
        location_id: UUID | None,
        item_id: UUID | None,
    ) -> list[StockRow]: ...
    async def get_item_stock(
        self, organization_id: UUID, warehouse_id: UUID, item_id: UUID
    ) -> StockRow | None: ...
    async def list_movements(
        self,
        organization_id: UUID,
        item_id: UUID,
        location_ids: tuple[UUID, ...],
        warehouse_id: UUID | None,
    ) -> list[MovementRow]: ...
    async def list_transactions(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> list[InventoryTransaction]: ...
    async def detail(
        self, organization_id: UUID, transaction_id: UUID
    ) -> TransactionDetail | None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class InventoryReferenceValidator(Protocol):
    async def validate(
        self, organization_id: UUID, reference_type: str, reference_id: UUID
    ) -> None: ...
