from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.inventory.domain.entities import (
    InventoryCount,
    InventoryTransfer,
    WriteOff,
    WriteOffReason,
)


class InventoryOperationsRepository(Protocol):
    async def next_number(self, document: str) -> str: ...

    async def list_reasons(self, organization_id: UUID) -> list[WriteOffReason]: ...
    async def get_reason(
        self, organization_id: UUID, reason_id: UUID, *, lock: bool = False
    ) -> WriteOffReason | None: ...
    async def add_reason(self, reason: WriteOffReason) -> None: ...
    async def update_reason(
        self, organization_id: UUID, reason_id: UUID, name: str, is_active: bool, now: datetime
    ) -> None: ...

    async def add_writeoff(self, value: WriteOff) -> None: ...
    async def list_writeoffs(self, organization_id: UUID) -> list[WriteOff]: ...
    async def get_writeoff(
        self, organization_id: UUID, writeoff_id: UUID, *, lock: bool = False
    ) -> WriteOff | None: ...
    async def replace_writeoff(self, value: WriteOff) -> None: ...
    async def post_writeoff(
        self,
        organization_id: UUID,
        writeoff_id: UUID,
        user_id: UUID,
        transaction_id: UUID,
        total_cost: Decimal,
        now: datetime,
    ) -> None: ...
    async def reverse_writeoff(
        self, organization_id: UUID, writeoff_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    async def count_snapshots(
        self,
        organization_id: UUID,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...] | None,
    ) -> dict[UUID, Decimal]: ...
    async def add_count(self, value: InventoryCount) -> None: ...
    async def list_counts(self, organization_id: UUID) -> list[InventoryCount]: ...
    async def get_count(
        self, organization_id: UUID, count_id: UUID, *, lock: bool = False
    ) -> InventoryCount | None: ...
    async def update_count_lines(
        self,
        organization_id: UUID,
        count_id: UUID,
        values: dict[UUID, tuple[Decimal, Decimal | None]],
        now: datetime,
    ) -> None: ...
    async def post_count(
        self,
        organization_id: UUID,
        count_id: UUID,
        user_id: UUID,
        transaction_id: UUID | None,
        snapshots: dict[UUID, tuple[Decimal, Decimal, Decimal | None, Decimal]],
        now: datetime,
    ) -> None: ...
    async def cancel_count(
        self, organization_id: UUID, count_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    async def add_transfer(self, value: InventoryTransfer) -> None: ...
    async def list_transfers(self, organization_id: UUID) -> list[InventoryTransfer]: ...
    async def get_transfer(
        self, organization_id: UUID, transfer_id: UUID, *, lock: bool = False
    ) -> InventoryTransfer | None: ...
    async def replace_transfer(self, value: InventoryTransfer) -> None: ...
    async def post_transfer(
        self,
        organization_id: UUID,
        transfer_id: UUID,
        user_id: UUID,
        out_transaction_id: UUID,
        in_transaction_id: UUID,
        now: datetime,
    ) -> None: ...
    async def reverse_transfer(
        self, organization_id: UUID, transfer_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
