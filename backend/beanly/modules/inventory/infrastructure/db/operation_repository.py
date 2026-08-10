from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    InventoryTransferStatus,
    WriteOffStatus,
)
from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.inventory.infrastructure.db.models import (
    InventoryCountLineModel,
    InventoryCountModel,
    InventoryItemModel,
    InventoryTransferLineModel,
    InventoryTransferModel,
    StockBalanceModel,
    WriteOffLineModel,
    WriteOffModel,
    WriteOffReasonModel,
)

_DOCUMENTS = {
    "writeoff": ("WO", "inventory_writeoff_number_seq", WriteOffModel),
    "count": ("IC", "inventory_count_number_seq", InventoryCountModel),
    "transfer": ("TR", "inventory_transfer_number_seq", InventoryTransferModel),
}


class SqlAlchemyInventoryOperationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_number(self, document: str) -> str:
        prefix, sequence, model = _DOCUMENTS[document]
        if self.session.get_bind().dialect.name == "postgresql":
            value = await self.session.scalar(text(f"SELECT nextval('{sequence}')"))
        else:
            value = (await self.session.scalar(select(func.count(model.id)))) + 1
        return f"{prefix}-{value:06d}"

    async def list_reasons(self, organization_id: UUID) -> list[WriteOffReason]:
        models = await self.session.scalars(
            select(WriteOffReasonModel)
            .where(WriteOffReasonModel.organization_id == organization_id)
            .order_by(WriteOffReasonModel.name, WriteOffReasonModel.id)
        )
        return [self._reason(value) for value in models]

    async def get_reason(
        self, organization_id: UUID, reason_id: UUID, *, lock: bool = False
    ) -> WriteOffReason | None:
        statement = select(WriteOffReasonModel).where(
            WriteOffReasonModel.organization_id == organization_id,
            WriteOffReasonModel.id == reason_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return self._reason(model) if model else None

    async def add_reason(self, reason: WriteOffReason) -> None:
        self.session.add(
            WriteOffReasonModel(
                id=reason.id,
                organization_id=reason.organization_id,
                name=reason.name,
                is_active=reason.is_active,
                created_at=reason.created_at,
                updated_at=reason.updated_at,
            )
        )
        await self.session.flush()

    async def update_reason(
        self, organization_id: UUID, reason_id: UUID, name: str, is_active: bool, now
    ) -> None:
        await self.session.execute(
            update(WriteOffReasonModel)
            .where(
                WriteOffReasonModel.organization_id == organization_id,
                WriteOffReasonModel.id == reason_id,
            )
            .values(name=name, is_active=is_active, updated_at=now)
        )
        await self.session.flush()

    async def add_writeoff(self, value: WriteOff) -> None:
        self.session.add(self._writeoff_model(value))
        await self.session.flush()
        self.session.add_all(self._writeoff_line_model(line) for line in value.lines)
        await self.session.flush()

    async def list_writeoffs(self, organization_id: UUID) -> list[WriteOff]:
        models = await self.session.scalars(
            select(WriteOffModel)
            .where(WriteOffModel.organization_id == organization_id)
            .order_by(WriteOffModel.occurred_at.desc(), WriteOffModel.id.desc())
        )
        return [await self._writeoff(value) for value in models]

    async def get_writeoff(
        self, organization_id: UUID, writeoff_id: UUID, *, lock: bool = False
    ) -> WriteOff | None:
        statement = select(WriteOffModel).where(
            WriteOffModel.organization_id == organization_id,
            WriteOffModel.id == writeoff_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return await self._writeoff(model) if model else None

    async def replace_writeoff(self, value: WriteOff) -> None:
        await self.session.execute(
            update(WriteOffModel)
            .where(
                WriteOffModel.organization_id == value.organization_id,
                WriteOffModel.id == value.id,
            )
            .values(
                warehouse_id=value.warehouse_id,
                location_id=value.location_id,
                reason_id=value.reason_id,
                occurred_at=value.occurred_at,
                note=value.note,
                updated_at=value.updated_at,
            )
        )
        await self.session.execute(
            delete(WriteOffLineModel).where(WriteOffLineModel.writeoff_id == value.id)
        )
        self.session.add_all(self._writeoff_line_model(line) for line in value.lines)
        await self.session.flush()

    async def post_writeoff(
        self,
        organization_id: UUID,
        writeoff_id: UUID,
        user_id: UUID,
        transaction_id: UUID,
        total_cost: Decimal,
        now,
    ) -> None:
        await self.session.execute(
            update(WriteOffModel)
            .where(
                WriteOffModel.organization_id == organization_id,
                WriteOffModel.id == writeoff_id,
            )
            .values(
                status=WriteOffStatus.POSTED.value,
                posted_by=user_id,
                posted_at=now,
                inventory_transaction_id=transaction_id,
                total_cost_amount=total_cost,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def reverse_writeoff(
        self, organization_id: UUID, writeoff_id: UUID, user_id: UUID, now
    ) -> None:
        await self.session.execute(
            update(WriteOffModel)
            .where(
                WriteOffModel.organization_id == organization_id,
                WriteOffModel.id == writeoff_id,
            )
            .values(
                status=WriteOffStatus.REVERSED.value,
                reversed_by=user_id,
                reversed_at=now,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def count_snapshots(
        self,
        organization_id: UUID,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...] | None,
    ) -> dict[UUID, Decimal]:
        statement = (
            select(InventoryItemModel.id, StockBalanceModel.quantity)
            .outerjoin(
                StockBalanceModel,
                (StockBalanceModel.inventory_item_id == InventoryItemModel.id)
                & (StockBalanceModel.warehouse_id == warehouse_id),
            )
            .where(InventoryItemModel.organization_id == organization_id)
        )
        if item_ids is None:
            statement = statement.where(
                or_(
                    InventoryItemModel.is_active.is_(True),
                    StockBalanceModel.quantity != 0,
                )
            )
        else:
            statement = statement.where(InventoryItemModel.id.in_(item_ids))
        rows = (await self.session.execute(statement.order_by(InventoryItemModel.id))).all()
        return {item_id: quantity or Decimal(0) for item_id, quantity in rows}

    async def add_count(self, value: InventoryCount) -> None:
        self.session.add(
            InventoryCountModel(
                id=value.id,
                organization_id=value.organization_id,
                location_id=value.location_id,
                warehouse_id=value.warehouse_id,
                number=value.number,
                type=value.type.value,
                status=value.status.value,
                snapshot_at=value.snapshot_at,
                started_by=value.started_by,
                posted_by=value.posted_by,
                posted_at=value.posted_at,
                cancelled_by=value.cancelled_by,
                cancelled_at=value.cancelled_at,
                inventory_transaction_id=value.inventory_transaction_id,
                note=value.note,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
        )
        await self.session.flush()
        self.session.add_all(
            InventoryCountLineModel(
                id=line.id,
                inventory_count_id=line.inventory_count_id,
                inventory_item_id=line.inventory_item_id,
                expected_quantity=line.expected_quantity,
                counted_quantity=line.counted_quantity,
                current_quantity_before_post=line.current_quantity_before_post,
                difference_quantity=line.difference_quantity,
                difference_cost_amount=line.difference_cost_amount,
                unit_cost_amount=line.unit_cost_amount,
                created_at=line.created_at,
                updated_at=line.updated_at,
            )
            for line in value.lines
        )
        await self.session.flush()

    async def list_counts(self, organization_id: UUID) -> list[InventoryCount]:
        models = await self.session.scalars(
            select(InventoryCountModel)
            .where(InventoryCountModel.organization_id == organization_id)
            .order_by(InventoryCountModel.snapshot_at.desc(), InventoryCountModel.id.desc())
        )
        return [await self._count(value) for value in models]

    async def get_count(
        self, organization_id: UUID, count_id: UUID, *, lock: bool = False
    ) -> InventoryCount | None:
        statement = select(InventoryCountModel).where(
            InventoryCountModel.organization_id == organization_id,
            InventoryCountModel.id == count_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return await self._count(model) if model else None

    async def update_count_lines(
        self,
        organization_id: UUID,
        count_id: UUID,
        values: dict[UUID, tuple[Decimal, Decimal | None]],
        now,
    ) -> None:
        valid_count = select(InventoryCountModel.id).where(
            InventoryCountModel.organization_id == organization_id,
            InventoryCountModel.id == count_id,
        )
        for item_id, (counted, unit_cost) in values.items():
            await self.session.execute(
                update(InventoryCountLineModel)
                .where(
                    InventoryCountLineModel.inventory_count_id.in_(valid_count),
                    InventoryCountLineModel.inventory_item_id == item_id,
                )
                .values(
                    counted_quantity=counted,
                    unit_cost_amount=unit_cost,
                    updated_at=now,
                )
            )
        await self.session.flush()

    async def post_count(
        self,
        organization_id: UUID,
        count_id: UUID,
        user_id: UUID,
        transaction_id: UUID | None,
        snapshots: dict[UUID, tuple[Decimal, Decimal, Decimal | None, Decimal]],
        now,
    ) -> None:
        for item_id, (current, difference, cost, unit_cost) in snapshots.items():
            await self.session.execute(
                update(InventoryCountLineModel)
                .where(
                    InventoryCountLineModel.inventory_count_id == count_id,
                    InventoryCountLineModel.inventory_item_id == item_id,
                )
                .values(
                    current_quantity_before_post=current,
                    difference_quantity=difference,
                    difference_cost_amount=cost,
                    unit_cost_amount=unit_cost,
                    updated_at=now,
                )
            )
        await self.session.execute(
            update(InventoryCountModel)
            .where(
                InventoryCountModel.organization_id == organization_id,
                InventoryCountModel.id == count_id,
            )
            .values(
                status=InventoryCountStatus.POSTED.value,
                posted_by=user_id,
                posted_at=now,
                inventory_transaction_id=transaction_id,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def cancel_count(
        self, organization_id: UUID, count_id: UUID, user_id: UUID, now
    ) -> None:
        await self.session.execute(
            update(InventoryCountModel)
            .where(
                InventoryCountModel.organization_id == organization_id,
                InventoryCountModel.id == count_id,
            )
            .values(
                status=InventoryCountStatus.CANCELLED.value,
                cancelled_by=user_id,
                cancelled_at=now,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def add_transfer(self, value: InventoryTransfer) -> None:
        self.session.add(self._transfer_model(value))
        await self.session.flush()
        self.session.add_all(self._transfer_line_model(line) for line in value.lines)
        await self.session.flush()

    async def list_transfers(self, organization_id: UUID) -> list[InventoryTransfer]:
        models = await self.session.scalars(
            select(InventoryTransferModel)
            .where(InventoryTransferModel.organization_id == organization_id)
            .order_by(InventoryTransferModel.occurred_at.desc(), InventoryTransferModel.id.desc())
        )
        return [await self._transfer(value) for value in models]

    async def get_transfer(
        self, organization_id: UUID, transfer_id: UUID, *, lock: bool = False
    ) -> InventoryTransfer | None:
        statement = select(InventoryTransferModel).where(
            InventoryTransferModel.organization_id == organization_id,
            InventoryTransferModel.id == transfer_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return await self._transfer(model) if model else None

    async def replace_transfer(self, value: InventoryTransfer) -> None:
        await self.session.execute(
            update(InventoryTransferModel)
            .where(
                InventoryTransferModel.organization_id == value.organization_id,
                InventoryTransferModel.id == value.id,
            )
            .values(
                source_location_id=value.source_location_id,
                source_warehouse_id=value.source_warehouse_id,
                destination_location_id=value.destination_location_id,
                destination_warehouse_id=value.destination_warehouse_id,
                occurred_at=value.occurred_at,
                note=value.note,
                updated_at=value.updated_at,
            )
        )
        await self.session.execute(
            delete(InventoryTransferLineModel).where(
                InventoryTransferLineModel.transfer_id == value.id
            )
        )
        self.session.add_all(self._transfer_line_model(line) for line in value.lines)
        await self.session.flush()

    async def post_transfer(
        self,
        organization_id: UUID,
        transfer_id: UUID,
        user_id: UUID,
        out_transaction_id: UUID,
        in_transaction_id: UUID,
        now,
    ) -> None:
        await self.session.execute(
            update(InventoryTransferModel)
            .where(
                InventoryTransferModel.organization_id == organization_id,
                InventoryTransferModel.id == transfer_id,
            )
            .values(
                status=InventoryTransferStatus.POSTED.value,
                posted_by=user_id,
                posted_at=now,
                out_transaction_id=out_transaction_id,
                in_transaction_id=in_transaction_id,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def reverse_transfer(
        self, organization_id: UUID, transfer_id: UUID, user_id: UUID, now
    ) -> None:
        await self.session.execute(
            update(InventoryTransferModel)
            .where(
                InventoryTransferModel.organization_id == organization_id,
                InventoryTransferModel.id == transfer_id,
            )
            .values(
                status=InventoryTransferStatus.REVERSED.value,
                reversed_by=user_id,
                reversed_at=now,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    @staticmethod
    def _reason(model: WriteOffReasonModel) -> WriteOffReason:
        return WriteOffReason(
            model.id,
            model.organization_id,
            model.name,
            model.is_active,
            model.created_at,
            model.updated_at,
        )

    @staticmethod
    def _writeoff_line(model: WriteOffLineModel) -> WriteOffLine:
        return WriteOffLine(
            model.id,
            model.writeoff_id,
            model.inventory_item_id,
            model.quantity,
            UnitCode(model.unit_code),
            model.base_quantity,
            model.note,
            model.created_at,
            model.updated_at,
        )

    @staticmethod
    def _writeoff_line_model(line: WriteOffLine) -> WriteOffLineModel:
        return WriteOffLineModel(
            id=line.id,
            writeoff_id=line.writeoff_id,
            inventory_item_id=line.inventory_item_id,
            quantity=line.quantity,
            unit_code=line.unit_code.value,
            base_quantity=line.base_quantity,
            note=line.note,
            created_at=line.created_at,
            updated_at=line.updated_at,
        )

    @staticmethod
    def _writeoff_model(value: WriteOff) -> WriteOffModel:
        return WriteOffModel(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            warehouse_id=value.warehouse_id,
            number=value.number,
            reason_id=value.reason_id,
            status=value.status.value,
            occurred_at=value.occurred_at,
            note=value.note,
            created_by=value.created_by,
            posted_by=value.posted_by,
            posted_at=value.posted_at,
            reversed_by=value.reversed_by,
            reversed_at=value.reversed_at,
            inventory_transaction_id=value.inventory_transaction_id,
            total_cost_amount=value.total_cost_amount,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    async def _writeoff(self, model: WriteOffModel) -> WriteOff:
        lines = await self.session.scalars(
            select(WriteOffLineModel)
            .where(WriteOffLineModel.writeoff_id == model.id)
            .order_by(WriteOffLineModel.inventory_item_id)
        )
        return WriteOff(
            model.id,
            model.organization_id,
            model.location_id,
            model.warehouse_id,
            model.number,
            model.reason_id,
            WriteOffStatus(model.status),
            model.occurred_at,
            model.note,
            model.created_by,
            model.posted_by,
            model.posted_at,
            model.reversed_by,
            model.reversed_at,
            model.inventory_transaction_id,
            model.total_cost_amount,
            model.created_at,
            model.updated_at,
            tuple(self._writeoff_line(line) for line in lines),
        )

    @staticmethod
    def _count_line(model: InventoryCountLineModel) -> InventoryCountLine:
        return InventoryCountLine(
            model.id,
            model.inventory_count_id,
            model.inventory_item_id,
            model.expected_quantity,
            model.counted_quantity,
            model.current_quantity_before_post,
            model.difference_quantity,
            model.difference_cost_amount,
            model.unit_cost_amount,
            model.created_at,
            model.updated_at,
        )

    async def _count(self, model: InventoryCountModel) -> InventoryCount:
        lines = await self.session.scalars(
            select(InventoryCountLineModel)
            .where(InventoryCountLineModel.inventory_count_id == model.id)
            .order_by(InventoryCountLineModel.inventory_item_id)
        )
        return InventoryCount(
            model.id,
            model.organization_id,
            model.location_id,
            model.warehouse_id,
            model.number,
            InventoryCountType(model.type),
            InventoryCountStatus(model.status),
            model.snapshot_at,
            model.started_by,
            model.posted_by,
            model.posted_at,
            model.cancelled_by,
            model.cancelled_at,
            model.inventory_transaction_id,
            model.note,
            model.created_at,
            model.updated_at,
            tuple(self._count_line(line) for line in lines),
        )

    @staticmethod
    def _transfer_line(model: InventoryTransferLineModel) -> InventoryTransferLine:
        return InventoryTransferLine(
            model.id,
            model.transfer_id,
            model.inventory_item_id,
            model.quantity,
            UnitCode(model.unit_code),
            model.base_quantity,
            model.created_at,
            model.updated_at,
        )

    @staticmethod
    def _transfer_line_model(line: InventoryTransferLine) -> InventoryTransferLineModel:
        return InventoryTransferLineModel(
            id=line.id,
            transfer_id=line.transfer_id,
            inventory_item_id=line.inventory_item_id,
            quantity=line.quantity,
            unit_code=line.unit_code.value,
            base_quantity=line.base_quantity,
            created_at=line.created_at,
            updated_at=line.updated_at,
        )

    @staticmethod
    def _transfer_model(value: InventoryTransfer) -> InventoryTransferModel:
        return InventoryTransferModel(
            id=value.id,
            organization_id=value.organization_id,
            number=value.number,
            source_location_id=value.source_location_id,
            source_warehouse_id=value.source_warehouse_id,
            destination_location_id=value.destination_location_id,
            destination_warehouse_id=value.destination_warehouse_id,
            status=value.status.value,
            occurred_at=value.occurred_at,
            note=value.note,
            created_by=value.created_by,
            posted_by=value.posted_by,
            posted_at=value.posted_at,
            reversed_by=value.reversed_by,
            reversed_at=value.reversed_at,
            out_transaction_id=value.out_transaction_id,
            in_transaction_id=value.in_transaction_id,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    async def _transfer(self, model: InventoryTransferModel) -> InventoryTransfer:
        lines = await self.session.scalars(
            select(InventoryTransferLineModel)
            .where(InventoryTransferLineModel.transfer_id == model.id)
            .order_by(InventoryTransferLineModel.inventory_item_id)
        )
        return InventoryTransfer(
            model.id,
            model.organization_id,
            model.number,
            model.source_location_id,
            model.source_warehouse_id,
            model.destination_location_id,
            model.destination_warehouse_id,
            InventoryTransferStatus(model.status),
            model.occurred_at,
            model.note,
            model.created_by,
            model.posted_by,
            model.posted_at,
            model.reversed_by,
            model.reversed_at,
            model.out_transaction_id,
            model.in_transaction_id,
            model.created_at,
            model.updated_at,
            tuple(self._transfer_line(line) for line in lines),
        )
