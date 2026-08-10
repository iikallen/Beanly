from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from beanly.core.events import DomainEventSink
from beanly.core.money import MAX_NUMERIC_20_6
from beanly.modules.inventory.application.commands import CreateAndPostCommand, QuantityInput
from beanly.modules.inventory.application.operation_ports import InventoryOperationsRepository
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.entities import (
    InventoryCount,
    InventoryCountLine,
    InventoryTransfer,
    InventoryTransferLine,
    WriteOff,
    WriteOffLine,
    WriteOffReason,
)
from beanly.modules.inventory.domain.enums import (
    InventoryCountStatus,
    InventoryCountType,
    InventoryTransactionType,
    InventoryTransferStatus,
    WriteOffStatus,
)
from beanly.modules.inventory.domain.events import (
    InventoryCountCancelled,
    InventoryCountPosted,
    InventoryTransferPosted,
    InventoryTransferReversed,
    InventoryWriteOffPosted,
    InventoryWriteOffReversed,
)
from beanly.modules.inventory.domain.exceptions import (
    InvalidInventoryOperation,
    InvalidInventoryUnit,
    InventoryCountChanged,
    InventoryNotFound,
)
from beanly.modules.inventory.domain.value_objects import UnitCode, to_base_quantity
from beanly.modules.organizations.domain.entities import TenantContext


@dataclass(frozen=True, slots=True)
class OperationLineInput:
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    note: str | None = None


class InventoryOperationsService:
    def __init__(
        self,
        repository: InventoryOperationsRepository,
        inventory: InventoryService,
        sink: DomainEventSink,
    ) -> None:
        self.repository = repository
        self.inventory = inventory
        self.sink = sink

    async def list_reasons(self, context: TenantContext) -> list[WriteOffReason]:
        return await self.repository.list_reasons(context.organization_id)

    async def create_reason(self, context: TenantContext, name: str) -> WriteOffReason:
        now = datetime.now(UTC)
        reason = WriteOffReason(uuid4(), context.organization_id, _name(name), True, now, now)
        return await self._commit(reason, self.repository.add_reason(reason))

    async def update_reason(
        self,
        context: TenantContext,
        reason_id: UUID,
        *,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> WriteOffReason:
        try:
            reason = await self.repository.get_reason(
                context.organization_id, reason_id, lock=True
            )
            if reason is None:
                raise InventoryNotFound
            await self.repository.update_reason(
                context.organization_id,
                reason.id,
                _name(name) if name is not None else reason.name,
                is_active if is_active is not None else reason.is_active,
                datetime.now(UTC),
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        updated = await self.repository.get_reason(context.organization_id, reason_id)
        if updated is None:
            raise RuntimeError("Write-off reason disappeared")
        return updated

    async def create_writeoff(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        reason_id: UUID,
        occurred_at: datetime,
        note: str | None,
        lines: tuple[OperationLineInput, ...],
    ) -> WriteOff:
        reason = await self.repository.get_reason(context.organization_id, reason_id)
        if reason is None or not reason.is_active:
            raise InvalidInventoryOperation("Active write-off reason is required")
        warehouse, prepared = await self._prepare_document_lines(
            context, warehouse_id, lines
        )
        now = datetime.now(UTC)
        value = WriteOff(
            uuid4(),
            context.organization_id,
            warehouse.location_id,
            warehouse.id,
            await self.repository.next_number("writeoff"),
            reason.id,
            WriteOffStatus.DRAFT,
            _aware(occurred_at),
            _note(note),
            context.user_id,
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
        )
        value = replace(
            value,
            lines=tuple(
                WriteOffLine(
                    uuid4(),
                    value.id,
                    item_id,
                    quantity,
                    unit,
                    base,
                    line_note,
                    now,
                    now,
                )
                for item_id, quantity, unit, base, line_note in prepared
            ),
        )
        return await self._commit(value, self.repository.add_writeoff(value))

    async def list_writeoffs(self, context: TenantContext) -> list[WriteOff]:
        allowed = set(await self.inventory.accessible_location_ids(context))
        values = await self.repository.list_writeoffs(context.organization_id)
        return [value for value in values if value.location_id in allowed]

    async def get_writeoff(self, context: TenantContext, writeoff_id: UUID) -> WriteOff:
        value = await self.repository.get_writeoff(context.organization_id, writeoff_id)
        if value is None:
            raise InventoryNotFound
        await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
        return value

    async def update_writeoff(
        self,
        context: TenantContext,
        writeoff_id: UUID,
        warehouse_id: UUID,
        reason_id: UUID,
        occurred_at: datetime,
        note: str | None,
        lines: tuple[OperationLineInput, ...],
    ) -> WriteOff:
        try:
            value = await self.repository.get_writeoff(
                context.organization_id, writeoff_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
            if value.status != WriteOffStatus.DRAFT:
                raise InvalidInventoryOperation("Posted write-offs are immutable")
            reason = await self.repository.get_reason(context.organization_id, reason_id)
            if reason is None or not reason.is_active:
                raise InvalidInventoryOperation("Active write-off reason is required")
            warehouse, prepared = await self._prepare_document_lines(
                context, warehouse_id, lines
            )
            now = datetime.now(UTC)
            value = replace(
                value,
                warehouse_id=warehouse.id,
                location_id=warehouse.location_id,
                reason_id=reason.id,
                occurred_at=_aware(occurred_at),
                note=_note(note),
                updated_at=now,
                lines=tuple(
                    WriteOffLine(
                        uuid4(),
                        value.id,
                        item_id,
                        quantity,
                        unit,
                        base,
                        line_note,
                        now,
                        now,
                    )
                    for item_id, quantity, unit, base, line_note in prepared
                ),
            )
            await self.repository.replace_writeoff(value)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_writeoff(context, writeoff_id)

    async def post_writeoff(self, context: TenantContext, writeoff_id: UUID) -> WriteOff:
        try:
            value = await self.repository.get_writeoff(
                context.organization_id, writeoff_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
            if value.status == WriteOffStatus.POSTED:
                await self.repository.rollback()
                return value
            if value.status != WriteOffStatus.DRAFT:
                raise InvalidInventoryOperation("Write-off cannot be posted")
            reason = await self.repository.get_reason(context.organization_id, value.reason_id)
            if reason is None or not reason.is_active:
                raise InvalidInventoryOperation("Active write-off reason is required")
            staged = await self.inventory.create_and_post_staged(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    value.warehouse_id,
                    InventoryTransactionType.WRITE_OFF,
                    value.note,
                    tuple(
                        QuantityInput(
                            line.inventory_item_id,
                            -line.base_quantity,
                            _base_unit(line.unit_code),
                        )
                        for line in value.lines
                    ),
                    f"writeoff:{value.id}",
                    "WRITE_OFF",
                    value.id,
                ),
                validate_reference=False,
            )
            total = -sum(
                (line.total_cost_amount or Decimal(0) for line in staged.detail.lines),
                Decimal(0),
            )
            now = datetime.now(UTC)
            await self.repository.post_writeoff(
                context.organization_id,
                value.id,
                context.user_id,
                staged.detail.transaction.id,
                total,
                now,
            )
            await self.sink.stage_many(
                (*staged.events, InventoryWriteOffPosted(
                    context.organization_id,
                    value.id,
                    staged.detail.transaction.id,
                    value.reason_id,
                    total,
                ))
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_writeoff(context, writeoff_id)

    async def reverse_writeoff(self, context: TenantContext, writeoff_id: UUID) -> WriteOff:
        try:
            value = await self.repository.get_writeoff(
                context.organization_id, writeoff_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
            if value.status != WriteOffStatus.POSTED or value.inventory_transaction_id is None:
                raise InvalidInventoryOperation("Only a posted write-off can be reversed")
            staged = await self.inventory.reverse_staged(
                context,
                value.inventory_transaction_id,
                f"writeoff:{value.id}:reverse",
                allow_source_controlled=True,
            )
            now = datetime.now(UTC)
            await self.repository.reverse_writeoff(
                context.organization_id, value.id, context.user_id, now
            )
            await self.sink.stage_many(
                (*staged.events, InventoryWriteOffReversed(
                    context.organization_id,
                    value.id,
                    value.inventory_transaction_id,
                    staged.detail.transaction.id,
                ))
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_writeoff(context, writeoff_id)

    async def create_count(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        type_: InventoryCountType,
        item_ids: tuple[UUID, ...],
        note: str | None,
    ) -> InventoryCount:
        warehouse = await self.inventory.ensure_warehouse_access(context, warehouse_id)
        selected: tuple[UUID, ...] | None
        if type_ == InventoryCountType.PARTIAL:
            if not item_ids:
                raise InvalidInventoryOperation("Partial count requires inventory items")
            _, items = await self.inventory.validate_purchase_resources(
                context, warehouse_id, tuple(sorted(set(item_ids), key=str))
            )
            selected = tuple(item.id for item in items)
        else:
            if item_ids:
                raise InvalidInventoryOperation("Full count selects inventory items automatically")
            selected = None
        now = datetime.now(UTC)
        snapshots = await self.repository.count_snapshots(
            context.organization_id, warehouse_id, selected
        )
        value = InventoryCount(
            uuid4(),
            context.organization_id,
            warehouse.location_id,
            warehouse.id,
            await self.repository.next_number("count"),
            type_,
            InventoryCountStatus.COUNTING,
            now,
            context.user_id,
            None,
            None,
            None,
            None,
            None,
            _note(note),
            now,
            now,
        )
        value = replace(
            value,
            lines=tuple(
                InventoryCountLine(
                    uuid4(), value.id, item_id, quantity, None, None, None, None, None, now, now
                )
                for item_id, quantity in snapshots.items()
            ),
        )
        return await self._commit(value, self.repository.add_count(value))

    async def list_counts(self, context: TenantContext) -> list[InventoryCount]:
        allowed = set(await self.inventory.accessible_location_ids(context))
        values = await self.repository.list_counts(context.organization_id)
        return [value for value in values if value.location_id in allowed]

    async def get_count(self, context: TenantContext, count_id: UUID) -> InventoryCount:
        value = await self.repository.get_count(context.organization_id, count_id)
        if value is None:
            raise InventoryNotFound
        await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
        return value

    async def update_count_lines(
        self,
        context: TenantContext,
        count_id: UUID,
        lines: tuple[OperationLineInput, ...],
        unit_costs: dict[UUID, Decimal | None],
    ) -> InventoryCount:
        try:
            value = await self.repository.get_count(
                context.organization_id, count_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
            if value.status != InventoryCountStatus.COUNTING:
                raise InvalidInventoryOperation("Posted or cancelled counts are immutable")
            existing = {line.inventory_item_id for line in value.lines}
            values: dict[UUID, tuple[Decimal, Decimal | None]] = {}
            for line in lines:
                if line.inventory_item_id not in existing:
                    raise InventoryNotFound
                item = await self.inventory.get_item_for_operation(
                    context.organization_id, line.inventory_item_id, include_inactive=True
                )
                quantity = _to_nonnegative_base(
                    line.quantity, line.unit_code, item.base_unit
                )
                values[line.inventory_item_id] = (
                    quantity,
                    _nonnegative_cost(unit_costs.get(line.inventory_item_id)),
                )
            await self.repository.update_count_lines(
                context.organization_id, value.id, values, datetime.now(UTC)
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_count(context, count_id)

    async def post_count(
        self, context: TenantContext, count_id: UUID, confirm_stock_changes: bool
    ) -> InventoryCount:
        try:
            value = await self.repository.get_count(
                context.organization_id, count_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            warehouse = await self.inventory.ensure_warehouse_access(
                context, value.warehouse_id
            )
            if value.status == InventoryCountStatus.POSTED:
                await self.repository.rollback()
                return value
            if value.status != InventoryCountStatus.COUNTING:
                raise InvalidInventoryOperation("Inventory count cannot be posted")
            if any(line.counted_quantity is None for line in value.lines):
                raise InvalidInventoryOperation("Every count line needs an actual quantity")
            item_ids = tuple(line.inventory_item_id for line in value.lines)
            balances = await self.inventory.lock_operation_balances(
                context,
                warehouse.id,
                item_ids,
                datetime.now(UTC),
            )
            moved_items = await self.inventory.changed_items_since(
                context, value.warehouse_id, item_ids, value.snapshot_at
            )
            changed = [
                {
                    "inventory_item_id": str(line.inventory_item_id),
                    "expected_at_start": str(line.expected_quantity),
                    "current": str(balances[line.inventory_item_id].quantity),
                }
                for line in value.lines
                if line.inventory_item_id in moved_items
                or line.expected_quantity != balances[line.inventory_item_id].quantity
            ]
            if changed and not confirm_stock_changes:
                raise InventoryCountChanged(changed)
            deltas = {
                line.inventory_item_id: line.counted_quantity
                - balances[line.inventory_item_id].quantity
                for line in value.lines
                if line.counted_quantity is not None
            }
            nonzero = {item_id: delta for item_id, delta in deltas.items() if delta != 0}
            for line in value.lines:
                delta = nonzero.get(line.inventory_item_id)
                if (
                    delta is not None
                    and delta > 0
                    and balances[line.inventory_item_id].quantity == 0
                    and balances[line.inventory_item_id].average_unit_cost == 0
                    and line.unit_cost_amount is None
                ):
                    raise InvalidInventoryOperation(
                        "Unit cost is required when current WAC is unavailable"
                    )
            staged = None
            if nonzero:
                count_inputs = []
                for line in value.lines:
                    if line.inventory_item_id not in nonzero:
                        continue
                    item = await self.inventory.get_item_for_operation(
                        context.organization_id,
                        line.inventory_item_id,
                        include_inactive=True,
                    )
                    count_inputs.append(
                        QuantityInput(
                            line.inventory_item_id,
                            nonzero[line.inventory_item_id],
                            _base_unit_for_item(item),
                            (
                                line.unit_cost_amount
                                if line.unit_cost_amount is not None
                                else None
                            )
                            if nonzero[line.inventory_item_id] > 0
                            else None,
                        )
                    )
                staged = await self.inventory.create_and_post_staged(
                    context,
                    CreateAndPostCommand(
                        context.organization_id,
                        context.user_id,
                        value.warehouse_id,
                        InventoryTransactionType.ADJUSTMENT,
                        f"Inventory count {value.number}",
                        tuple(count_inputs),
                        f"inventory-count:{value.id}",
                        "INVENTORY_COUNT",
                        value.id,
                    ),
                    validate_reference=False,
                    allow_inactive_items=True,
                )
            posted_lines = {
                line.inventory_item_id: line for line in (staged.detail.lines if staged else ())
            }
            snapshots = {
                line.inventory_item_id: (
                    balances[line.inventory_item_id].quantity,
                    deltas[line.inventory_item_id],
                    (
                        posted_lines[line.inventory_item_id].total_cost_amount
                        if line.inventory_item_id in posted_lines
                        else Decimal(0)
                    ),
                    (
                        posted_lines[line.inventory_item_id].unit_cost_amount
                        if line.inventory_item_id in posted_lines
                        else balances[line.inventory_item_id].average_unit_cost
                    ),
                )
                for line in value.lines
            }
            loss = sum(
                (-snapshot[2] for snapshot in snapshots.values() if snapshot[2] < 0),
                Decimal(0),
            )
            gain = sum(
                (snapshot[2] for snapshot in snapshots.values() if snapshot[2] > 0),
                Decimal(0),
            )
            if max(loss, gain) > MAX_NUMERIC_20_6:
                raise InvalidInventoryOperation(
                    "Inventory count variance exceeds the finance ledger limit"
                )
            transaction_id = staged.detail.transaction.id if staged else None
            now = datetime.now(UTC)
            await self.repository.post_count(
                context.organization_id,
                value.id,
                context.user_id,
                transaction_id,
                snapshots,
                now,
            )
            await self.sink.stage_many(
                (*((staged.events) if staged else ()), InventoryCountPosted(
                    context.organization_id, value.id, transaction_id
                ))
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_count(context, count_id)

    async def cancel_count(self, context: TenantContext, count_id: UUID) -> InventoryCount:
        try:
            value = await self.repository.get_count(
                context.organization_id, count_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            await self.inventory.ensure_warehouse_access(context, value.warehouse_id)
            if value.status != InventoryCountStatus.COUNTING:
                raise InvalidInventoryOperation("Only a counting inventory can be cancelled")
            await self.repository.cancel_count(
                context.organization_id, value.id, context.user_id, datetime.now(UTC)
            )
            await self.sink.stage_many(
                (InventoryCountCancelled(context.organization_id, value.id),)
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_count(context, count_id)

    async def create_transfer(
        self,
        context: TenantContext,
        source_warehouse_id: UUID,
        destination_warehouse_id: UUID,
        occurred_at: datetime,
        note: str | None,
        lines: tuple[OperationLineInput, ...],
    ) -> InventoryTransfer:
        if source_warehouse_id == destination_warehouse_id:
            raise InvalidInventoryOperation("Source and destination warehouses must differ")
        source, prepared = await self._prepare_document_lines(
            context, source_warehouse_id, lines
        )
        destination = await self.inventory.ensure_warehouse_access(
            context, destination_warehouse_id
        )
        now = datetime.now(UTC)
        value = InventoryTransfer(
            uuid4(),
            context.organization_id,
            await self.repository.next_number("transfer"),
            source.location_id,
            source.id,
            destination.location_id,
            destination.id,
            InventoryTransferStatus.DRAFT,
            _aware(occurred_at),
            _note(note),
            context.user_id,
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
        )
        value = replace(
            value,
            lines=tuple(
                InventoryTransferLine(
                    uuid4(), value.id, item_id, quantity, unit, base, now, now
                )
                for item_id, quantity, unit, base, _ in prepared
            ),
        )
        return await self._commit(value, self.repository.add_transfer(value))

    async def list_transfers(self, context: TenantContext) -> list[InventoryTransfer]:
        allowed = set(await self.inventory.accessible_location_ids(context))
        values = await self.repository.list_transfers(context.organization_id)
        return [
            value
            for value in values
            if value.source_location_id in allowed and value.destination_location_id in allowed
        ]

    async def get_transfer(self, context: TenantContext, transfer_id: UUID) -> InventoryTransfer:
        value = await self.repository.get_transfer(context.organization_id, transfer_id)
        if value is None:
            raise InventoryNotFound
        await self.inventory.ensure_warehouse_access(context, value.source_warehouse_id)
        await self.inventory.ensure_warehouse_access(context, value.destination_warehouse_id)
        return value

    async def update_transfer(
        self,
        context: TenantContext,
        transfer_id: UUID,
        source_warehouse_id: UUID,
        destination_warehouse_id: UUID,
        occurred_at: datetime,
        note: str | None,
        lines: tuple[OperationLineInput, ...],
    ) -> InventoryTransfer:
        try:
            value = await self.repository.get_transfer(
                context.organization_id, transfer_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            await self.inventory.ensure_warehouse_access(
                context, value.source_warehouse_id
            )
            await self.inventory.ensure_warehouse_access(
                context, value.destination_warehouse_id
            )
            if value.status != InventoryTransferStatus.DRAFT:
                raise InvalidInventoryOperation("Posted transfers are immutable")
            if source_warehouse_id == destination_warehouse_id:
                raise InvalidInventoryOperation("Source and destination warehouses must differ")
            source, prepared = await self._prepare_document_lines(
                context, source_warehouse_id, lines
            )
            destination = await self.inventory.ensure_warehouse_access(
                context, destination_warehouse_id
            )
            now = datetime.now(UTC)
            value = replace(
                value,
                source_location_id=source.location_id,
                source_warehouse_id=source.id,
                destination_location_id=destination.location_id,
                destination_warehouse_id=destination.id,
                occurred_at=_aware(occurred_at),
                note=_note(note),
                updated_at=now,
                lines=tuple(
                    InventoryTransferLine(
                        uuid4(), value.id, item_id, quantity, unit, base, now, now
                    )
                    for item_id, quantity, unit, base, _ in prepared
                ),
            )
            await self.repository.replace_transfer(value)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_transfer(context, transfer_id)

    async def post_transfer(self, context: TenantContext, transfer_id: UUID) -> InventoryTransfer:
        try:
            value = await self.repository.get_transfer(
                context.organization_id, transfer_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            source = await self.inventory.ensure_warehouse_access(
                context, value.source_warehouse_id
            )
            destination = await self.inventory.ensure_warehouse_access(
                context, value.destination_warehouse_id
            )
            if value.status == InventoryTransferStatus.POSTED:
                await self.repository.rollback()
                return value
            if value.status != InventoryTransferStatus.DRAFT:
                raise InvalidInventoryOperation("Transfer cannot be posted")
            item_ids = tuple(line.inventory_item_id for line in value.lines)
            costs = await self.inventory.current_costs(
                context, source.id, item_ids
            )
            if missing := set(item_ids) - costs.keys():
                raise InvalidInventoryOperation(
                    f"TRANSFER_COST_UNAVAILABLE:{','.join(sorted(map(str, missing)))}"
                )
            await self.inventory.lock_transfer_balances(
                context, source.id, destination.id, item_ids, datetime.now(UTC)
            )
            out = await self.inventory.create_and_post_staged(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    source.id,
                    InventoryTransactionType.TRANSFER_OUT,
                    value.note,
                    tuple(
                        QuantityInput(
                            line.inventory_item_id,
                            -line.base_quantity,
                            _base_unit(line.unit_code),
                        )
                        for line in value.lines
                    ),
                    f"transfer:{value.id}:out",
                    "TRANSFER",
                    value.id,
                ),
                validate_reference=False,
            )
            out_lines = {line.inventory_item_id: line for line in out.detail.lines}
            incoming = await self.inventory.create_and_post_staged(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    destination.id,
                    InventoryTransactionType.TRANSFER_IN,
                    value.note,
                    tuple(
                        QuantityInput(
                            line.inventory_item_id,
                            line.base_quantity,
                            _base_unit(line.unit_code),
                            total_cost_amount=-out_lines[line.inventory_item_id].total_cost_amount,
                        )
                        for line in value.lines
                    ),
                    f"transfer:{value.id}:in",
                    "TRANSFER",
                    value.id,
                ),
                validate_reference=False,
            )
            now = datetime.now(UTC)
            await self.repository.post_transfer(
                context.organization_id,
                value.id,
                context.user_id,
                out.detail.transaction.id,
                incoming.detail.transaction.id,
                now,
            )
            await self.sink.stage_many(
                (*out.events, *incoming.events, InventoryTransferPosted(
                    context.organization_id,
                    value.id,
                    out.detail.transaction.id,
                    incoming.detail.transaction.id,
                ))
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_transfer(context, transfer_id)

    async def reverse_transfer(
        self, context: TenantContext, transfer_id: UUID
    ) -> InventoryTransfer:
        try:
            value = await self.repository.get_transfer(
                context.organization_id, transfer_id, lock=True
            )
            if value is None:
                raise InventoryNotFound
            source = await self.inventory.ensure_warehouse_access(
                context, value.source_warehouse_id
            )
            destination = await self.inventory.ensure_warehouse_access(
                context, value.destination_warehouse_id
            )
            if (
                value.status != InventoryTransferStatus.POSTED
                or value.out_transaction_id is None
                or value.in_transaction_id is None
            ):
                raise InvalidInventoryOperation("Only a posted transfer can be reversed")
            item_ids = tuple(line.inventory_item_id for line in value.lines)
            await self.inventory.lock_transfer_balances(
                context, source.id, destination.id, item_ids, datetime.now(UTC)
            )
            in_reversal = await self.inventory.reverse_staged(
                context,
                value.in_transaction_id,
                f"transfer:{value.id}:in:reverse",
                allow_source_controlled=True,
            )
            out_reversal = await self.inventory.reverse_staged(
                context,
                value.out_transaction_id,
                f"transfer:{value.id}:out:reverse",
                allow_source_controlled=True,
            )
            await self.repository.reverse_transfer(
                context.organization_id, value.id, context.user_id, datetime.now(UTC)
            )
            await self.sink.stage_many(
                (*in_reversal.events, *out_reversal.events, InventoryTransferReversed(
                    context.organization_id,
                    value.id,
                    out_reversal.detail.transaction.id,
                    in_reversal.detail.transaction.id,
                ))
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_transfer(context, transfer_id)

    async def _prepare_document_lines(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        lines: tuple[OperationLineInput, ...],
    ):
        if not lines:
            raise InvalidInventoryOperation("At least one line is required")
        if len({line.inventory_item_id for line in lines}) != len(lines):
            raise InvalidInventoryOperation("Duplicate item lines are not allowed")
        warehouse, items = await self.inventory.validate_purchase_resources(
            context, warehouse_id, tuple(line.inventory_item_id for line in lines)
        )
        by_id = {item.id: item for item in items}
        prepared = []
        for line in lines:
            base = to_base_quantity(
                line.quantity, line.unit_code, by_id[line.inventory_item_id].base_unit
            )
            if base <= 0:
                raise InvalidInventoryUnit("Operation quantities must be positive")
            prepared.append(
                (
                    line.inventory_item_id,
                    line.quantity,
                    line.unit_code,
                    base,
                    _note(line.note),
                )
            )
        return warehouse, tuple(prepared)

    async def _commit(self, value, operation):
        try:
            await operation
            await self.repository.commit()
            return value
        except Exception:
            await self.repository.rollback()
            raise


def _name(value: str) -> str:
    result = value.strip()
    if not result or len(result) > 150:
        raise ValueError("Name must contain between 1 and 150 characters")
    return result


def _note(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if not result:
        return None
    if len(result) > 1000:
        raise ValueError("Note is too long")
    return result


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Datetime must include timezone")
    return value.astimezone(UTC)


def _base_unit(unit: UnitCode) -> UnitCode:
    return unit.base_unit


def _base_unit_for_item(item) -> UnitCode:
    return item.base_unit


def _nonnegative_cost(value: Decimal | None) -> Decimal | None:
    if value is not None and (
        not value.is_finite()
        or value < 0
        or value.as_tuple().exponent < -6
        or (value != 0 and value.adjusted() > 13)
    ):
        raise ValueError("Unit cost is outside NUMERIC(20, 6)")
    return value


def _to_nonnegative_base(
    value: Decimal, unit: UnitCode, base_unit: UnitCode
) -> Decimal:
    if value < 0:
        raise InvalidInventoryUnit("Counted quantity cannot be negative")
    if value == 0:
        if unit.base_unit != base_unit:
            raise InvalidInventoryUnit("Unit is incompatible with the inventory item")
        return Decimal(0)
    return to_base_quantity(value, unit, base_unit)
