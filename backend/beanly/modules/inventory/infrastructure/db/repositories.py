from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.inventory.domain.costing import inventory_value
from beanly.modules.inventory.domain.entities import (
    GlobalMovementRow,
    InventoryItem,
    InventoryTransaction,
    InventoryTransactionLine,
    MovementRow,
    StockBalance,
    StockRow,
    TransactionDetail,
    Warehouse,
)
from beanly.modules.inventory.domain.enums import (
    InventoryTransactionStatus,
    InventoryTransactionType,
)
from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.inventory.infrastructure.db.mappers import (
    to_item,
    to_line,
    to_transaction,
    to_warehouse,
)
from beanly.modules.inventory.infrastructure.db.models import (
    InventoryCountModel,
    InventoryItemModel,
    InventoryTransactionLineModel,
    InventoryTransactionModel,
    StockBalanceModel,
    WarehouseModel,
)


class SqlAlchemyInventoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_warehouse(self, warehouse: Warehouse) -> Warehouse:
        model = WarehouseModel(
            id=warehouse.id,
            organization_id=warehouse.organization_id,
            location_id=warehouse.location_id,
            name=warehouse.name,
            is_active=warehouse.is_active,
            created_at=warehouse.created_at,
            updated_at=warehouse.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_warehouse(model)

    async def list_warehouses(self, organization_id: UUID) -> list[Warehouse]:
        models = await self.session.scalars(
            select(WarehouseModel)
            .where(WarehouseModel.organization_id == organization_id)
            .order_by(WarehouseModel.created_at, WarehouseModel.id)
        )
        return [to_warehouse(model) for model in models]

    async def get_warehouse(self, organization_id: UUID, warehouse_id: UUID) -> Warehouse | None:
        model = await self.session.scalar(
            select(WarehouseModel).where(
                WarehouseModel.organization_id == organization_id,
                WarehouseModel.id == warehouse_id,
                WarehouseModel.is_active.is_(True),
            )
        )
        return to_warehouse(model) if model else None

    async def add_item(self, item: InventoryItem) -> InventoryItem:
        model = InventoryItemModel(
            id=item.id,
            organization_id=item.organization_id,
            name=item.name,
            sku=item.sku,
            base_unit=item.base_unit.value,
            is_active=item.is_active,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_item(model)

    async def list_items(self, organization_id: UUID) -> list[InventoryItem]:
        models = await self.session.scalars(
            select(InventoryItemModel)
            .where(InventoryItemModel.organization_id == organization_id)
            .order_by(InventoryItemModel.name, InventoryItemModel.id)
        )
        return [to_item(model) for model in models]

    async def get_item(
        self,
        organization_id: UUID,
        item_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> InventoryItem | None:
        statement = select(InventoryItemModel).where(
            InventoryItemModel.organization_id == organization_id,
            InventoryItemModel.id == item_id,
        )
        if not include_inactive:
            statement = statement.where(InventoryItemModel.is_active.is_(True))
        model = await self.session.scalar(statement)
        return to_item(model) if model else None

    async def get_items_by_ids(
        self, organization_id: UUID, item_ids: tuple[UUID, ...]
    ) -> list[InventoryItem]:
        if not item_ids:
            return []
        models = await self.session.scalars(
            select(InventoryItemModel).where(
                InventoryItemModel.organization_id == organization_id,
                InventoryItemModel.id.in_(item_ids),
                InventoryItemModel.is_active.is_(True),
            )
        )
        return [to_item(model) for model in models]

    async def get_current_costs(
        self, organization_id: UUID, warehouse_id: UUID, item_ids: tuple[UUID, ...]
    ) -> dict[UUID, Decimal]:
        if not item_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    StockBalanceModel.inventory_item_id,
                    StockBalanceModel.average_unit_cost,
                ).where(
                    StockBalanceModel.organization_id == organization_id,
                    StockBalanceModel.warehouse_id == warehouse_id,
                    StockBalanceModel.inventory_item_id.in_(item_ids),
                )
            )
        ).all()
        # A present Decimal(0) is intentionally different from a missing balance row.
        return {item_id: average_unit_cost for item_id, average_unit_cost in rows}

    async def changed_items_since(
        self,
        organization_id: UUID,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
        since,
    ) -> set[UUID]:
        if not item_ids:
            return set()
        values = await self.session.scalars(
            select(InventoryTransactionLineModel.inventory_item_id)
            .join(
                InventoryTransactionModel,
                InventoryTransactionModel.id == InventoryTransactionLineModel.transaction_id,
            )
            .where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.warehouse_id == warehouse_id,
                InventoryTransactionModel.status.in_(
                    (
                        InventoryTransactionStatus.POSTED.value,
                        InventoryTransactionStatus.REVERSED.value,
                    )
                ),
                InventoryTransactionModel.posted_at >= since,
                InventoryTransactionLineModel.inventory_item_id.in_(item_ids),
            )
        )
        return set(values)

    async def add_transaction(self, transaction: InventoryTransaction) -> InventoryTransaction:
        model = InventoryTransactionModel(
            id=transaction.id,
            organization_id=transaction.organization_id,
            location_id=transaction.location_id,
            warehouse_id=transaction.warehouse_id,
            type=transaction.type.value,
            status=transaction.status.value,
            reference_type=transaction.reference_type,
            reference_id=transaction.reference_id,
            idempotency_key=transaction.idempotency_key,
            note=transaction.note,
            created_by=transaction.created_by,
            created_at=transaction.created_at,
            posted_at=transaction.posted_at,
            reversal_of_id=transaction.reversal_of_id,
        )
        self.session.add(model)
        await self.session.flush()
        return to_transaction(model)

    async def add_lines(self, lines: tuple[InventoryTransactionLine, ...]) -> None:
        self.session.add_all(
            InventoryTransactionLineModel(
                id=line.id,
                transaction_id=line.transaction_id,
                inventory_item_id=line.inventory_item_id,
                quantity_delta=line.quantity_delta,
                requested_unit_cost_amount=line.requested_unit_cost_amount,
                requested_total_cost_amount=line.requested_total_cost_amount,
                unit_cost_amount=line.unit_cost_amount,
                total_cost_amount=line.total_cost_amount,
                quantity_after=line.quantity_after,
                average_unit_cost_after=line.average_unit_cost_after,
                created_at=line.created_at,
            )
            for line in lines
        )
        await self.session.flush()

    async def get_transaction(
        self, organization_id: UUID, transaction_id: UUID, *, lock: bool = False
    ) -> InventoryTransaction | None:
        statement = select(InventoryTransactionModel).where(
            InventoryTransactionModel.organization_id == organization_id,
            InventoryTransactionModel.id == transaction_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return to_transaction(model) if model else None

    async def get_by_idempotency_key(
        self, organization_id: UUID, key: str
    ) -> TransactionDetail | None:
        model = await self.session.scalar(
            select(InventoryTransactionModel).where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.idempotency_key == key,
            )
        )
        return await self._detail(model) if model else None

    async def get_reversal(
        self, organization_id: UUID, original_id: UUID
    ) -> TransactionDetail | None:
        model = await self.session.scalar(
            select(InventoryTransactionModel).where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.reversal_of_id == original_id,
            )
        )
        return await self._detail(model) if model else None

    async def get_lines(
        self, organization_id: UUID, transaction_id: UUID
    ) -> tuple[InventoryTransactionLine, ...]:
        models = await self.session.scalars(
            select(InventoryTransactionLineModel)
            .join(
                InventoryTransactionModel,
                InventoryTransactionModel.id == InventoryTransactionLineModel.transaction_id,
            )
            .where(InventoryTransactionLineModel.transaction_id == transaction_id)
            .where(InventoryTransactionModel.organization_id == organization_id)
            .order_by(
                InventoryTransactionLineModel.inventory_item_id,
                InventoryTransactionLineModel.id,
            )
        )
        return tuple(to_line(model) for model in models)

    async def mark_status(
        self,
        organization_id: UUID,
        transaction_id: UUID,
        status: InventoryTransactionStatus,
        posted_at,
    ) -> None:
        values: dict[str, object] = {"status": status.value}
        if posted_at is not None:
            values["posted_at"] = posted_at
        await self.session.execute(
            update(InventoryTransactionModel)
            .where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.id == transaction_id,
            )
            .values(**values)
        )
        await self.session.flush()

    async def lock_balances(
        self,
        organization_id: UUID,
        location_id: UUID,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
        now,
    ) -> dict[UUID, StockBalance]:
        ordered_ids = tuple(sorted(set(item_ids), key=str))
        dialect = self.session.get_bind().dialect.name
        insert_factory = postgresql_insert if dialect == "postgresql" else sqlite_insert
        for item_id in ordered_ids:
            insert = insert_factory(StockBalanceModel).values(
                id=uuid4(),
                organization_id=organization_id,
                location_id=location_id,
                warehouse_id=warehouse_id,
                inventory_item_id=item_id,
                quantity=Decimal(0),
                average_unit_cost=Decimal(0),
                updated_at=now,
            )
            await self.session.execute(
                insert.on_conflict_do_nothing(
                    index_elements=["warehouse_id", "inventory_item_id"]
                )
            )
        models = await self.session.scalars(
            select(StockBalanceModel)
            .where(
                StockBalanceModel.organization_id == organization_id,
                StockBalanceModel.warehouse_id == warehouse_id,
                StockBalanceModel.inventory_item_id.in_(ordered_ids),
            )
            .order_by(StockBalanceModel.inventory_item_id)
            .with_for_update()
        )
        balances = {
            model.inventory_item_id: StockBalance(
                model.id,
                model.organization_id,
                model.location_id,
                model.warehouse_id,
                model.inventory_item_id,
                model.quantity,
                model.average_unit_cost,
                model.updated_at,
            )
            for model in models
        }
        if set(balances) != set(ordered_ids):
            raise RuntimeError("Could not lock every inventory balance")
        return balances

    async def lock_balances_across_warehouses(
        self,
        organization_id: UUID,
        warehouse_item_pairs: tuple[tuple[UUID, UUID, UUID], ...],
        now,
    ) -> dict[tuple[UUID, UUID], StockBalance]:
        ordered = tuple(
            sorted(set(warehouse_item_pairs), key=lambda value: (str(value[1]), str(value[2])))
        )
        dialect = self.session.get_bind().dialect.name
        insert_factory = postgresql_insert if dialect == "postgresql" else sqlite_insert
        for location_id, warehouse_id, item_id in ordered:
            insert = insert_factory(StockBalanceModel).values(
                id=uuid4(),
                organization_id=organization_id,
                location_id=location_id,
                warehouse_id=warehouse_id,
                inventory_item_id=item_id,
                quantity=Decimal(0),
                average_unit_cost=Decimal(0),
                updated_at=now,
            )
            await self.session.execute(
                insert.on_conflict_do_nothing(
                    index_elements=["warehouse_id", "inventory_item_id"]
                )
            )
        keys = tuple((warehouse_id, item_id) for _, warehouse_id, item_id in ordered)
        if not keys:
            return {}
        models = await self.session.scalars(
            select(StockBalanceModel)
            .where(
                StockBalanceModel.organization_id == organization_id,
                tuple_(
                    StockBalanceModel.warehouse_id,
                    StockBalanceModel.inventory_item_id,
                ).in_(keys),
            )
            .order_by(StockBalanceModel.warehouse_id, StockBalanceModel.inventory_item_id)
            .with_for_update()
        )
        balances = {
            (model.warehouse_id, model.inventory_item_id): StockBalance(
                model.id,
                model.organization_id,
                model.location_id,
                model.warehouse_id,
                model.inventory_item_id,
                model.quantity,
                model.average_unit_cost,
                model.updated_at,
            )
            for model in models
        }
        if set(balances) != set(keys):
            raise RuntimeError("Could not lock every inventory balance")
        return balances

    async def update_balance(
        self,
        organization_id: UUID,
        balance_id: UUID,
        quantity: Decimal,
        average_unit_cost: Decimal,
        now,
    ) -> None:
        await self.session.execute(
            update(StockBalanceModel)
            .where(
                StockBalanceModel.organization_id == organization_id,
                StockBalanceModel.id == balance_id,
            )
            .values(
                quantity=quantity,
                average_unit_cost=average_unit_cost,
                updated_at=now,
            )
        )

    async def update_line_snapshot(
        self,
        organization_id: UUID,
        line_id: UUID,
        unit_cost_amount: Decimal,
        total_cost_amount: Decimal,
        quantity_after: Decimal,
        average_unit_cost_after: Decimal,
    ) -> None:
        transaction_ids = select(InventoryTransactionModel.id).where(
            InventoryTransactionModel.organization_id == organization_id
        )
        await self.session.execute(
            update(InventoryTransactionLineModel)
            .where(
                InventoryTransactionLineModel.id == line_id,
                InventoryTransactionLineModel.transaction_id.in_(transaction_ids),
            )
            .values(
                unit_cost_amount=unit_cost_amount,
                total_cost_amount=total_cost_amount,
                quantity_after=quantity_after,
                average_unit_cost_after=average_unit_cost_after,
            )
        )
        await self.session.flush()

    async def list_stock(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        warehouse_id: UUID | None,
        location_id: UUID | None,
        item_id: UUID | None,
    ) -> list[StockRow]:
        if not location_ids:
            return []
        statement = (
            select(StockBalanceModel, InventoryItemModel)
            .join(
                InventoryItemModel,
                InventoryItemModel.id == StockBalanceModel.inventory_item_id,
            )
            .where(
                StockBalanceModel.organization_id == organization_id,
                StockBalanceModel.location_id.in_(location_ids),
            )
        )
        if warehouse_id is not None:
            statement = statement.where(StockBalanceModel.warehouse_id == warehouse_id)
        if location_id is not None:
            statement = statement.where(StockBalanceModel.location_id == location_id)
        if item_id is not None:
            statement = statement.where(StockBalanceModel.inventory_item_id == item_id)
        rows = (
            await self.session.execute(
                statement.order_by(InventoryItemModel.name, StockBalanceModel.warehouse_id)
            )
        ).all()
        return [self._stock_row(balance, item) for balance, item in rows]

    async def get_item_stock(
        self, organization_id: UUID, warehouse_id: UUID, item_id: UUID
    ) -> StockRow | None:
        row = (
            await self.session.execute(
                select(InventoryItemModel, StockBalanceModel)
                .outerjoin(
                    StockBalanceModel,
                    (StockBalanceModel.inventory_item_id == InventoryItemModel.id)
                    & (StockBalanceModel.warehouse_id == warehouse_id),
                )
                .where(
                    InventoryItemModel.organization_id == organization_id,
                    InventoryItemModel.id == item_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        item, balance = row
        if balance is None:
            return StockRow(
                warehouse_id,
                item.id,
                item.name,
                item.sku,
                Decimal(0),
                UnitCode(item.base_unit),
                Decimal(0),
                Decimal(0),
                None,
            )
        return self._stock_row(balance, item)

    async def list_movements(
        self,
        organization_id: UUID,
        item_id: UUID,
        location_ids: tuple[UUID, ...],
        warehouse_id: UUID | None,
    ) -> list[MovementRow]:
        if not location_ids:
            return []
        statement = (
            select(InventoryTransactionModel, InventoryTransactionLineModel)
            .join(
                InventoryTransactionLineModel,
                InventoryTransactionLineModel.transaction_id == InventoryTransactionModel.id,
            )
            .where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.location_id.in_(location_ids),
                InventoryTransactionModel.status.in_(
                    [
                        InventoryTransactionStatus.POSTED.value,
                        InventoryTransactionStatus.REVERSED.value,
                    ]
                ),
                InventoryTransactionLineModel.inventory_item_id == item_id,
            )
        )
        if warehouse_id is not None:
            statement = statement.where(InventoryTransactionModel.warehouse_id == warehouse_id)
        rows = (
            await self.session.execute(
                statement.order_by(
                    InventoryTransactionModel.posted_at.desc(),
                    InventoryTransactionModel.id.desc(),
                )
            )
        ).all()
        return [
            MovementRow(
                transaction.id,
                InventoryTransactionType(transaction.type),
                InventoryTransactionStatus(transaction.status),
                line.quantity_delta,
                line.unit_cost_amount,
                line.total_cost_amount,
                line.quantity_after,
                line.average_unit_cost_after,
                transaction.reference_type,
                transaction.reference_id,
                transaction.note,
                transaction.posted_at,
                transaction.created_at,
            )
            for transaction, line in rows
        ]

    async def list_global_movements(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        warehouse_id: UUID | None,
        location_id: UUID | None,
        item_id: UUID | None,
        type_: str | None,
        date_from,
        date_to,
        reference_type: str | None,
    ) -> list[GlobalMovementRow]:
        if not location_ids:
            return []
        statement = (
            select(
                InventoryTransactionModel,
                InventoryTransactionLineModel,
                InventoryItemModel,
            )
            .join(
                InventoryTransactionLineModel,
                InventoryTransactionLineModel.transaction_id
                == InventoryTransactionModel.id,
            )
            .join(
                InventoryItemModel,
                InventoryItemModel.id == InventoryTransactionLineModel.inventory_item_id,
            )
            .where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.location_id.in_(location_ids),
                InventoryTransactionModel.status.in_(
                    (
                        InventoryTransactionStatus.POSTED.value,
                        InventoryTransactionStatus.REVERSED.value,
                    )
                ),
                InventoryTransactionModel.posted_at.is_not(None),
            )
        )
        filters = (
            (warehouse_id, InventoryTransactionModel.warehouse_id),
            (location_id, InventoryTransactionModel.location_id),
            (item_id, InventoryTransactionLineModel.inventory_item_id),
            (type_, InventoryTransactionModel.type),
            (reference_type, InventoryTransactionModel.reference_type),
        )
        for value, column in filters:
            if value is not None:
                statement = statement.where(column == value)
        if date_from is not None:
            statement = statement.where(InventoryTransactionModel.posted_at >= date_from)
        if date_to is not None:
            statement = statement.where(InventoryTransactionModel.posted_at <= date_to)
        rows = (
            await self.session.execute(
                statement.order_by(
                    InventoryTransactionModel.posted_at.desc(),
                    InventoryTransactionModel.id.desc(),
                    InventoryTransactionLineModel.id,
                )
            )
        ).all()
        return [
            GlobalMovementRow(
                transaction.id,
                transaction.warehouse_id,
                transaction.location_id,
                line.inventory_item_id,
                item.name,
                InventoryTransactionType(transaction.type),
                line.quantity_delta,
                UnitCode(item.base_unit),
                line.unit_cost_amount,
                line.total_cost_amount,
                transaction.reference_type,
                transaction.reference_id,
                transaction.note,
                transaction.posted_at,
            )
            for transaction, line, item in rows
        ]

    async def list_transactions(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> list[InventoryTransaction]:
        if not location_ids:
            return []
        models = await self.session.scalars(
            select(InventoryTransactionModel)
            .where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.location_id.in_(location_ids),
            )
            .order_by(
                InventoryTransactionModel.created_at.desc(),
                InventoryTransactionModel.id.desc(),
            )
        )
        return [to_transaction(model) for model in models]

    async def detail(self, organization_id: UUID, transaction_id: UUID) -> TransactionDetail | None:
        model = await self.session.scalar(
            select(InventoryTransactionModel).where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.id == transaction_id,
            )
        )
        return await self._detail(model) if model else None

    async def dashboard_inventory_health(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[Decimal, int, int]:
        if not location_ids:
            return Decimal(0), 0, 0
        stock_filter = (
            StockBalanceModel.organization_id == organization_id,
            StockBalanceModel.location_id.in_(location_ids),
        )
        negative_items = (
            select(
                StockBalanceModel.location_id,
                StockBalanceModel.inventory_item_id,
                func.sum(StockBalanceModel.quantity).label("quantity"),
            )
            .where(*stock_filter)
            .group_by(
                StockBalanceModel.location_id,
                StockBalanceModel.inventory_item_id,
            )
            .having(func.sum(StockBalanceModel.quantity) < 0)
            .subquery()
        )
        total_value, negative = (
            await self.session.execute(
                select(
                    select(
                        func.coalesce(
                            func.sum(
                                StockBalanceModel.quantity
                                * StockBalanceModel.average_unit_cost
                            ),
                            Decimal(0),
                        )
                    )
                    .where(*stock_filter)
                    .scalar_subquery(),
                    select(func.count()).select_from(negative_items).scalar_subquery(),
                )
            )
        ).one()
        active_counts = int(
            await self.session.scalar(
                select(func.count(InventoryCountModel.id)).where(
                    InventoryCountModel.organization_id == organization_id,
                    InventoryCountModel.location_id.in_(location_ids),
                    InventoryCountModel.status == "COUNTING",
                )
            )
            or 0
        )
        return Decimal(total_value), int(negative or 0), active_counts

    async def dashboard_negative_items(
        self, organization_id: UUID, location_ids: tuple[UUID, ...], limit: int
    ) -> tuple[tuple[UUID, UUID, str, Decimal, str], ...]:
        if not location_ids:
            return ()
        quantity = func.sum(StockBalanceModel.quantity)
        rows = await self.session.execute(
            select(
                InventoryItemModel.id,
                StockBalanceModel.location_id,
                InventoryItemModel.name,
                quantity,
                InventoryItemModel.base_unit,
            )
            .join(
                InventoryItemModel,
                InventoryItemModel.id == StockBalanceModel.inventory_item_id,
            )
            .where(
                StockBalanceModel.organization_id == organization_id,
                StockBalanceModel.location_id.in_(location_ids),
            )
            .group_by(
                InventoryItemModel.id,
                StockBalanceModel.location_id,
                InventoryItemModel.name,
                InventoryItemModel.base_unit,
            )
            .having(quantity < 0)
            .order_by(quantity, InventoryItemModel.name)
            .limit(limit)
        )
        return tuple(
            (item_id, location_id, name, Decimal(quantity), unit_code)
            for item_id, location_id, name, quantity, unit_code in rows
        )

    async def dashboard_active_counts(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[tuple[UUID, UUID, str], ...]:
        if not location_ids:
            return ()
        rows = await self.session.execute(
            select(
                InventoryCountModel.id,
                InventoryCountModel.location_id,
                InventoryCountModel.number,
            )
            .where(
                InventoryCountModel.organization_id == organization_id,
                InventoryCountModel.location_id.in_(location_ids),
                InventoryCountModel.status == "COUNTING",
            )
            .order_by(InventoryCountModel.snapshot_at, InventoryCountModel.id)
            .limit(5)
        )
        return tuple(rows)

    async def _detail(self, model: InventoryTransactionModel) -> TransactionDetail:
        return TransactionDetail(
            to_transaction(model),
            await self.get_lines(model.organization_id, model.id),
        )

    @staticmethod
    def _stock_row(balance: StockBalanceModel, item: InventoryItemModel) -> StockRow:
        return StockRow(
            balance.warehouse_id,
            item.id,
            item.name,
            item.sku,
            balance.quantity,
            UnitCode(item.base_unit),
            balance.average_unit_cost,
            inventory_value(balance.quantity, balance.average_unit_cost),
            balance.updated_at,
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
