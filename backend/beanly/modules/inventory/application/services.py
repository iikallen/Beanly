from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from beanly.core.events import DomainEventSink, NullDomainEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    CreateDraftCommand,
    CreateInventoryItemCommand,
    CreateWarehouseCommand,
    QuantityInput,
)
from beanly.modules.inventory.application.ports import (
    InventoryReferenceValidator,
    InventoryRepository,
)
from beanly.modules.inventory.domain.costing import WeightedAverageCostCalculator
from beanly.modules.inventory.domain.entities import (
    GlobalMovementRow,
    InventoryItem,
    InventoryTransaction,
    InventoryTransactionLine,
    InventoryValuation,
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
from beanly.modules.inventory.domain.events import (
    InventoryCostUpdated,
    InventoryTransactionPosted,
    InventoryTransactionReversed,
    InventoryValuationChanged,
    StockAdjusted,
    StockWentNegative,
)
from beanly.modules.inventory.domain.exceptions import (
    DuplicateInventoryResource,
    IdempotencyConflict,
    InvalidInventoryOperation,
    InvalidInventoryUnit,
    InventoryNotFound,
    SourceControlledTransaction,
)
from beanly.modules.inventory.domain.value_objects import BASE_UNITS, to_base_quantity
from beanly.modules.organizations.application.queries.get_organization import (
    GetOrganizationQuery,
)
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.domain.permissions import Permission


@dataclass(frozen=True, slots=True)
class StagedInventoryTransaction:
    detail: TransactionDetail
    events: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class PreparedLine:
    inventory_item_id: UUID
    quantity_delta: Decimal
    requested_unit_cost_amount: Decimal | None
    requested_total_cost_amount: Decimal | None


class RejectingInventoryReferenceValidator:
    async def validate(
        self, organization_id: UUID, reference_type: str, reference_id: UUID
    ) -> None:
        del organization_id, reference_type, reference_id
        raise InvalidInventoryOperation(
            "Referenced source aggregate is not available in this stage"
        )


class InventoryService:
    def __init__(
        self,
        repository: InventoryRepository,
        organizations: OrganizationService,
        sink: DomainEventSink | None = None,
        reference_validator: InventoryReferenceValidator | None = None,
        audit: SecurityAuditRecorder | None = None,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.sink = sink or NullDomainEventSink()
        self.reference_validator = reference_validator or RejectingInventoryReferenceValidator()
        self.costing = WeightedAverageCostCalculator()
        self.audit = audit

    async def create_warehouse(
        self, context: TenantContext, command: CreateWarehouseCommand
    ) -> Warehouse:
        await self._ensure_location(context, command.location_id)
        now = datetime.now(UTC)
        warehouse = Warehouse(
            uuid4(),
            context.organization_id,
            command.location_id,
            _name(command.name),
            True,
            now,
            now,
        )
        try:
            created = await self.repository.add_warehouse(warehouse)
            await self.repository.commit()
            return created
        except Exception:
            await self.repository.rollback()
            raise

    async def list_warehouses(self, context: TenantContext) -> list[Warehouse]:
        allowed = set(await self._accessible_location_ids(context))
        warehouses = await self.repository.list_warehouses(context.organization_id)
        return [warehouse for warehouse in warehouses if warehouse.location_id in allowed]

    async def create_item(
        self, context: TenantContext, command: CreateInventoryItemCommand
    ) -> InventoryItem:
        if command.base_unit not in BASE_UNITS:
            raise InvalidInventoryUnit
        now = datetime.now(UTC)
        item = InventoryItem(
            uuid4(),
            context.organization_id,
            _name(command.name),
            _sku(command.sku),
            command.base_unit,
            True,
            now,
            now,
        )
        try:
            created = await self.repository.add_item(item)
            await self.repository.commit()
            return created
        except IntegrityError as exc:
            await self.repository.rollback()
            raise DuplicateInventoryResource from exc
        except Exception:
            await self.repository.rollback()
            raise

    async def list_items(self, context: TenantContext) -> list[InventoryItem]:
        return await self.repository.list_items(context.organization_id)

    async def validate_purchase_resources(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
    ) -> tuple[Warehouse, tuple[InventoryItem, ...]]:
        warehouse = await self._warehouse(context, warehouse_id)
        items = tuple([await self._item(context.organization_id, item_id) for item_id in item_ids])
        return warehouse, items

    async def list_stock(
        self,
        context: TenantContext,
        warehouse_id: UUID | None,
        location_id: UUID | None,
        item_id: UUID | None,
    ) -> list[StockRow]:
        allowed = await self._accessible_location_ids(context)
        if location_id is not None and location_id not in allowed:
            raise InventoryNotFound
        if warehouse_id is not None:
            warehouse = await self._warehouse(context, warehouse_id)
            if location_id is not None and warehouse.location_id != location_id:
                raise InventoryNotFound
        if item_id is not None:
            await self._item(context.organization_id, item_id)
        rows = await self.repository.list_stock(
            context.organization_id, allowed, warehouse_id, location_id, item_id
        )
        return self._redact_costs(context, rows)

    async def get_item_stock(
        self, context: TenantContext, item_id: UUID, warehouse_id: UUID
    ) -> StockRow:
        await self._warehouse(context, warehouse_id)
        await self._item(context.organization_id, item_id)
        row = await self.repository.get_item_stock(context.organization_id, warehouse_id, item_id)
        if row is None:
            raise InventoryNotFound
        return self._redact_costs(context, [row])[0]

    async def valuation(
        self,
        context: TenantContext,
        warehouse_id: UUID | None,
        location_id: UUID | None,
    ) -> InventoryValuation:
        if Permission.INVENTORY_READ not in context.permissions:
            raise OrganizationAccessDenied
        rows = await self.list_stock(context, warehouse_id, location_id, None)
        organization = await self.organizations.get_organization(
            GetOrganizationQuery(context.user_id, context.organization_id)
        )
        total = sum((row.inventory_value or Decimal(0) for row in rows), Decimal(0))
        return InventoryValuation(organization.currency_code, total, tuple(rows))

    async def list_movements(
        self, context: TenantContext, item_id: UUID, warehouse_id: UUID | None
    ) -> list[MovementRow]:
        await self._item(context.organization_id, item_id)
        if warehouse_id is not None:
            await self._warehouse(context, warehouse_id)
        return await self.repository.list_movements(
            context.organization_id,
            item_id,
            await self._accessible_location_ids(context),
            warehouse_id,
        )

    async def list_global_movements(
        self,
        context: TenantContext,
        warehouse_id: UUID | None,
        location_id: UUID | None,
        item_id: UUID | None,
        type_: InventoryTransactionType | None,
        date_from: datetime | None,
        date_to: datetime | None,
        reference_type: str | None,
    ) -> list[GlobalMovementRow]:
        if any(value is not None and value.utcoffset() is None for value in (date_from, date_to)):
            raise ValueError("Movement dates must include timezone")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        allowed = await self._accessible_location_ids(context)
        if location_id is not None and location_id not in allowed:
            raise InventoryNotFound
        if warehouse_id is not None:
            await self._warehouse(context, warehouse_id)
        if item_id is not None:
            await self._item(context.organization_id, item_id, include_inactive=True)
        return await self.repository.list_global_movements(
            context.organization_id,
            allowed,
            warehouse_id,
            location_id,
            item_id,
            type_.value if type_ else None,
            date_from,
            date_to,
            reference_type.strip().upper() if reference_type else None,
        )

    async def list_transactions(self, context: TenantContext) -> list[InventoryTransaction]:
        return await self.repository.list_transactions(
            context.organization_id, await self._accessible_location_ids(context)
        )

    async def get_transaction(
        self, context: TenantContext, transaction_id: UUID
    ) -> TransactionDetail:
        detail = await self.repository.detail(context.organization_id, transaction_id)
        if detail is None:
            raise InventoryNotFound
        await self._warehouse(context, detail.transaction.warehouse_id)
        return detail

    async def create_and_post(
        self, context: TenantContext, command: CreateAndPostCommand
    ) -> TransactionDetail:
        try:
            staged = await self.create_and_post_staged(context, command)
            await self.sink.stage_many(staged.events)
            if self.audit and command.type is InventoryTransactionType.ADJUSTMENT:
                await self.audit.record(
                    action="INVENTORY_MANUAL_ADJUSTMENT",
                    resource_type="inventory_transaction",
                    organization_id=context.organization_id,
                    actor_user_id=context.user_id,
                    resource_id=staged.detail.transaction.id,
                )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            return await self._existing_after_conflict(context, command, exc)
        except Exception:
            await self.repository.rollback()
            raise
        return staged.detail

    async def create_and_post_staged(
        self,
        context: TenantContext,
        command: CreateAndPostCommand,
        *,
        validate_reference: bool = True,
        allow_inactive_items: bool = False,
    ) -> StagedInventoryTransaction:
        warehouse = await self._warehouse(context, command.warehouse_id)
        note = _note(command.note)
        key = _idempotency_key(command.idempotency_key)
        reference_type, reference_id = _reference(command.reference_type, command.reference_id)
        if validate_reference and reference_type is not None and reference_id is not None:
            await self.reference_validator.validate(
                context.organization_id, reference_type, reference_id
            )
        lines = await self._prepare_lines(
            context.organization_id,
            command.lines,
            opening=command.type == InventoryTransactionType.OPENING_BALANCE,
            include_inactive=(
                command.type == InventoryTransactionType.SALE or allow_inactive_items
            ),
        )
        if not lines:
            raise InvalidInventoryOperation("At least one line is required")

        if key is not None:
            existing = await self.repository.get_by_idempotency_key(context.organization_id, key)
            if existing is not None:
                self._assert_same_request(
                    existing,
                    command.type,
                    warehouse.id,
                    note,
                    lines,
                    reference_type,
                    reference_id,
                )
                return StagedInventoryTransaction(existing, ())

        now = datetime.now(UTC)
        transaction = InventoryTransaction(
            uuid4(),
            context.organization_id,
            warehouse.location_id,
            warehouse.id,
            command.type,
            InventoryTransactionStatus.DRAFT,
            reference_type,
            reference_id,
            key,
            note,
            context.user_id,
            now,
            None,
            None,
        )
        persisted_lines = tuple(
            InventoryTransactionLine(
                id=uuid4(),
                transaction_id=transaction.id,
                inventory_item_id=line.inventory_item_id,
                quantity_delta=line.quantity_delta,
                requested_unit_cost_amount=line.requested_unit_cost_amount,
                requested_total_cost_amount=line.requested_total_cost_amount,
                unit_cost_amount=None,
                total_cost_amount=line.requested_total_cost_amount,
                quantity_after=None,
                average_unit_cost_after=None,
                created_at=now,
            )
            for line in lines
        )
        await self.repository.add_transaction(transaction)
        await self.repository.add_lines(persisted_lines)
        events = await self._post_in_transaction(context, transaction.id)
        detail = await self.repository.detail(context.organization_id, transaction.id)
        if detail is None:
            raise RuntimeError("Posted transaction disappeared")
        return StagedInventoryTransaction(detail, tuple(events))

    async def _existing_after_conflict(
        self,
        context: TenantContext,
        command: CreateAndPostCommand,
        exc: IntegrityError,
    ) -> TransactionDetail:
        key = _idempotency_key(command.idempotency_key)
        if key is None:
            raise DuplicateInventoryResource from exc
        existing = await self.repository.get_by_idempotency_key(context.organization_id, key)
        if existing is None:
            raise DuplicateInventoryResource from exc
        warehouse = await self._warehouse(context, command.warehouse_id)
        lines = await self._prepare_lines(
            context.organization_id,
            command.lines,
            opening=command.type == InventoryTransactionType.OPENING_BALANCE,
            include_inactive=command.type == InventoryTransactionType.SALE,
        )
        reference_type, reference_id = _reference(command.reference_type, command.reference_id)
        self._assert_same_request(
            existing,
            command.type,
            warehouse.id,
            _note(command.note),
            lines,
            reference_type,
            reference_id,
        )
        return existing

    async def create_draft(
        self, context: TenantContext, command: CreateDraftCommand
    ) -> TransactionDetail:
        warehouse = await self._warehouse(context, command.warehouse_id)
        now = datetime.now(UTC)
        transaction = InventoryTransaction(
            uuid4(),
            context.organization_id,
            warehouse.location_id,
            warehouse.id,
            command.type,
            InventoryTransactionStatus.DRAFT,
            None,
            None,
            _idempotency_key(command.idempotency_key),
            _note(command.note),
            context.user_id,
            now,
            None,
            None,
        )
        lines = await self._prepare_lines(context.organization_id, command.lines)
        persisted = tuple(
            InventoryTransactionLine(
                uuid4(),
                transaction.id,
                line.inventory_item_id,
                line.quantity_delta,
                line.requested_unit_cost_amount,
                line.requested_total_cost_amount,
                None,
                line.requested_total_cost_amount,
                None,
                None,
                now,
            )
            for line in lines
        )
        try:
            await self.repository.add_transaction(transaction)
            await self.repository.add_lines(persisted)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        detail = await self.repository.detail(context.organization_id, transaction.id)
        if detail is None:
            raise RuntimeError("Draft transaction disappeared")
        return detail

    async def add_line(
        self, context: TenantContext, transaction_id: UUID, value: QuantityInput
    ) -> TransactionDetail:
        try:
            transaction = await self.repository.get_transaction(
                context.organization_id, transaction_id, lock=True
            )
            if transaction is None:
                raise InventoryNotFound
            await self._warehouse(context, transaction.warehouse_id)
            if transaction.status != InventoryTransactionStatus.DRAFT:
                raise InvalidInventoryOperation("Posted transactions are immutable")
            lines = await self._prepare_lines(context.organization_id, (value,))
            now = datetime.now(UTC)
            await self.repository.add_lines(
                tuple(
                    InventoryTransactionLine(
                        uuid4(),
                        transaction.id,
                        line.inventory_item_id,
                        line.quantity_delta,
                        line.requested_unit_cost_amount,
                        line.requested_total_cost_amount,
                        None,
                        line.requested_total_cost_amount,
                        None,
                        None,
                        now,
                    )
                    for line in lines
                )
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        detail = await self.repository.detail(context.organization_id, transaction_id)
        if detail is None:
            raise RuntimeError("Transaction disappeared")
        return detail

    async def post_transaction(
        self, context: TenantContext, transaction_id: UUID
    ) -> TransactionDetail:
        try:
            events = await self._post_in_transaction(context, transaction_id)
            await self.sink.stage_many(tuple(events))
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_transaction(context, transaction_id)

    async def reverse(
        self,
        context: TenantContext,
        transaction_id: UUID,
        idempotency_key: str | None,
    ) -> TransactionDetail:
        try:
            staged = await self.reverse_staged(context, transaction_id, idempotency_key)
            await self.sink.stage_many(staged.events)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return staged.detail

    async def reverse_staged(
        self,
        context: TenantContext,
        transaction_id: UUID,
        idempotency_key: str | None,
        *,
        allow_source_controlled: bool = False,
    ) -> StagedInventoryTransaction:
        key = _idempotency_key(idempotency_key)
        original = await self.repository.get_transaction(
            context.organization_id, transaction_id, lock=True
        )
        if original is None:
            raise InventoryNotFound
        await self._warehouse(context, original.warehouse_id)
        if (
            original.reference_type
            in {
                "ORDER",
                "GOODS_RECEIPT",
                "WRITE_OFF",
                "INVENTORY_COUNT",
                "TRANSFER",
                "SUPPLIER_RETURN",
                "REFUND",
            }
            and not allow_source_controlled
        ):
            raise SourceControlledTransaction("SOURCE_CONTROLLED_TRANSACTION")
        if original.status == InventoryTransactionStatus.REVERSED:
            existing = await self.repository.get_reversal(context.organization_id, original.id)
            if (
                existing is not None
                and key is not None
                and key == existing.transaction.idempotency_key
            ):
                return StagedInventoryTransaction(existing, ())
            raise InvalidInventoryOperation("Transaction was already reversed")
        if (
            original.status != InventoryTransactionStatus.POSTED
            or original.reversal_of_id is not None
        ):
            raise InvalidInventoryOperation("Only posted original transactions can reverse")
        if key is not None:
            by_key = await self.repository.get_by_idempotency_key(context.organization_id, key)
            if by_key is not None:
                if by_key.transaction.reversal_of_id == original.id:
                    return StagedInventoryTransaction(by_key, ())
                raise IdempotencyConflict
        original_lines = await self.repository.get_lines(context.organization_id, original.id)
        now = datetime.now(UTC)
        reversal = replace(
            original,
            id=uuid4(),
            status=InventoryTransactionStatus.DRAFT,
            idempotency_key=key,
            note=f"Reversal: {original.note}" if original.note else "Reversal",
            created_by=context.user_id,
            created_at=now,
            posted_at=None,
            reversal_of_id=original.id,
        )
        reversal_lines = tuple(
            replace(
                line,
                id=uuid4(),
                transaction_id=reversal.id,
                quantity_delta=-line.quantity_delta,
                requested_unit_cost_amount=line.unit_cost_amount,
                requested_total_cost_amount=(
                    -line.total_cost_amount if line.total_cost_amount is not None else None
                ),
                unit_cost_amount=line.unit_cost_amount,
                total_cost_amount=(
                    -line.total_cost_amount if line.total_cost_amount is not None else None
                ),
                quantity_after=None,
                average_unit_cost_after=None,
                created_at=now,
            )
            for line in original_lines
        )
        await self.repository.add_transaction(reversal)
        await self.repository.add_lines(reversal_lines)
        events = await self._post_in_transaction(context, reversal.id)
        await self.repository.mark_status(
            context.organization_id,
            original.id,
            InventoryTransactionStatus.REVERSED,
            original.posted_at,
        )
        events.append(
            InventoryTransactionReversed(context.organization_id, original.id, reversal.id)
        )
        detail = await self.repository.detail(context.organization_id, reversal.id)
        if detail is None:
            raise RuntimeError("Reversal transaction disappeared")
        return StagedInventoryTransaction(detail, tuple(events))

    async def _post_in_transaction(
        self, context: TenantContext, transaction_id: UUID
    ) -> list[object]:
        transaction = await self.repository.get_transaction(
            context.organization_id, transaction_id, lock=True
        )
        if transaction is None:
            raise InventoryNotFound
        await self._warehouse(context, transaction.warehouse_id)
        if transaction.status == InventoryTransactionStatus.POSTED:
            return []
        if transaction.status != InventoryTransactionStatus.DRAFT:
            raise InvalidInventoryOperation("Transaction cannot be posted")
        lines = await self.repository.get_lines(context.organization_id, transaction.id)
        if not lines:
            raise InvalidInventoryOperation("Transaction has no lines")
        deltas: dict[UUID, Decimal] = defaultdict(Decimal)
        for line in lines:
            await self._item(
                context.organization_id,
                line.inventory_item_id,
                include_inactive=transaction.type == InventoryTransactionType.SALE,
            )
            deltas[line.inventory_item_id] += line.quantity_delta
        if any(delta == 0 for delta in deltas.values()):
            raise InvalidInventoryOperation("Net item movement cannot be zero")

        now = datetime.now(UTC)
        balances = await self.repository.lock_balances(
            context.organization_id,
            transaction.location_id,
            transaction.warehouse_id,
            tuple(deltas),
            now,
        )
        events: list[object] = []
        running = dict(balances)
        for line in lines:
            balance = running[line.inventory_item_id]
            try:
                result = self._calculate_line(transaction, line, balance)
            except ValueError as exc:
                raise InvalidInventoryOperation(str(exc)) from exc
            await self.repository.update_line_snapshot(
                context.organization_id,
                line.id,
                result.unit_cost_amount,
                result.total_cost_amount,
                result.quantity_after,
                result.average_unit_cost_after,
            )
            await self.repository.update_balance(
                context.organization_id,
                balance.id,
                result.quantity_after,
                result.average_unit_cost_after,
                now,
            )
            running[line.inventory_item_id] = replace(
                balance,
                quantity=result.quantity_after,
                average_unit_cost=result.average_unit_cost_after,
                updated_at=now,
            )
            events.append(
                InventoryCostUpdated(
                    context.organization_id,
                    transaction.warehouse_id,
                    line.inventory_item_id,
                    result.average_unit_cost_after,
                )
            )
        for item_id, balance in running.items():
            if balance.quantity < 0:
                events.append(
                    StockWentNegative(
                        context.organization_id,
                        transaction.warehouse_id,
                        item_id,
                        balance.quantity,
                    )
                )
        posted_at = datetime.now(UTC)
        await self.repository.mark_status(
            context.organization_id,
            transaction.id,
            InventoryTransactionStatus.POSTED,
            posted_at,
        )
        events.insert(0, InventoryTransactionPosted(context.organization_id, transaction.id))
        events.append(
            InventoryValuationChanged(
                context.organization_id,
                transaction.warehouse_id,
                transaction.id,
            )
        )
        if transaction.type == InventoryTransactionType.ADJUSTMENT:
            events.append(StockAdjusted(context.organization_id, transaction.id))
        return events

    async def _prepare_lines(
        self,
        organization_id: UUID,
        values: tuple[QuantityInput, ...],
        *,
        opening: bool = False,
        include_inactive: bool = False,
    ) -> tuple[PreparedLine, ...]:
        totals: dict[UUID, PreparedLine] = {}
        for value in values:
            item = await self._item(
                organization_id,
                value.inventory_item_id,
                include_inactive=include_inactive,
            )
            try:
                quantity = to_base_quantity(value.quantity, value.unit_code, item.base_unit)
            except ValueError as exc:
                raise InvalidInventoryUnit(str(exc)) from exc
            if opening and quantity <= 0:
                raise InvalidInventoryUnit("Opening quantities must be positive")
            if value.unit_cost_amount is not None and value.total_cost_amount is not None:
                raise InvalidInventoryUnit("Provide unit cost or total cost, not both")
            unit_cost = _base_unit_cost(value.unit_cost_amount, value.unit_code)
            total_cost = _cost_amount(value.total_cost_amount)
            if total_cost is not None:
                unit_cost = _cost_amount(total_cost / quantity)
            previous = totals.get(item.id)
            if previous is None:
                totals[item.id] = PreparedLine(item.id, quantity, unit_cost, total_cost)
                continue
            if previous.requested_unit_cost_amount != unit_cost:
                raise InvalidInventoryOperation("Duplicate item lines must use the same unit cost")
            totals[item.id] = PreparedLine(
                item.id,
                previous.quantity_delta + quantity,
                unit_cost,
                (
                    previous.requested_total_cost_amount + total_cost
                    if previous.requested_total_cost_amount is not None and total_cost is not None
                    else None
                ),
            )
        if any(line.quantity_delta == 0 for line in totals.values()):
            raise InvalidInventoryOperation("Net item movement cannot be zero")
        return tuple(line for _, line in sorted(totals.items(), key=lambda pair: str(pair[0])))

    @staticmethod
    def _assert_same_request(
        existing: TransactionDetail,
        type_: InventoryTransactionType,
        warehouse_id: UUID,
        note: str | None,
        lines: tuple[PreparedLine, ...],
        reference_type: str | None,
        reference_id: UUID | None,
    ) -> None:
        persisted = tuple(
            sorted(
                (
                    (
                        line.inventory_item_id,
                        line.quantity_delta,
                        line.requested_unit_cost_amount,
                        line.requested_total_cost_amount,
                    )
                    for line in existing.lines
                ),
                key=lambda pair: str(pair[0]),
            )
        )
        requested = tuple(
            (
                line.inventory_item_id,
                line.quantity_delta,
                line.requested_unit_cost_amount,
                line.requested_total_cost_amount,
            )
            for line in lines
        )
        if (
            existing.transaction.type != type_
            or existing.transaction.warehouse_id != warehouse_id
            or existing.transaction.note != note
            or persisted != requested
            or existing.transaction.reference_type != reference_type
            or existing.transaction.reference_id != reference_id
        ):
            raise IdempotencyConflict

    def _calculate_line(self, transaction, line, balance):
        if transaction.reversal_of_id is not None:
            if line.unit_cost_amount is None or line.total_cost_amount is None:
                raise ValueError("Original cost snapshot is missing")
            return self.costing.calculate(
                balance.quantity,
                balance.average_unit_cost,
                line.quantity_delta,
                reversal_unit_cost=line.unit_cost_amount,
                reversal_total_cost=line.total_cost_amount,
            )
        if line.quantity_delta < 0:
            if line.requested_unit_cost_amount is not None:
                raise ValueError("Outflow cost is determined by current WAC")
            return self.costing.calculate(
                balance.quantity,
                balance.average_unit_cost,
                line.quantity_delta,
            )

        incoming_unit = line.requested_unit_cost_amount
        incoming_total = line.total_cost_amount
        if transaction.type == InventoryTransactionType.OPENING_BALANCE:
            incoming_unit = incoming_unit if incoming_unit is not None else Decimal(0)
            incoming_total = None
        elif transaction.type == InventoryTransactionType.ADJUSTMENT:
            incoming_total = None
            if balance.quantity != 0 or balance.average_unit_cost != 0:
                if incoming_unit is not None and incoming_unit != balance.average_unit_cost:
                    raise ValueError("Positive adjustment must use current WAC")
                incoming_unit = balance.average_unit_cost
            elif incoming_unit is None:
                raise ValueError("Unit cost is required when current WAC is unavailable")
        elif transaction.type == InventoryTransactionType.PURCHASE:
            if incoming_total is None:
                raise ValueError("Purchase total acquisition cost is required")
            incoming_unit = None
        elif transaction.type == InventoryTransactionType.TRANSFER_IN:
            if incoming_total is None:
                raise ValueError("Transfer total acquisition cost is required")
            incoming_unit = None
        elif incoming_unit is None and incoming_total is None:
            raise ValueError("Incoming inventory cost is required")
        return self.costing.calculate(
            balance.quantity,
            balance.average_unit_cost,
            line.quantity_delta,
            incoming_unit,
            incoming_total,
        )

    @staticmethod
    def _redact_costs(context: TenantContext, rows: list[StockRow]) -> list[StockRow]:
        if Permission.INVENTORY_READ in context.permissions:
            return rows
        return [replace(row, average_unit_cost=None, inventory_value=None) for row in rows]

    async def _warehouse(self, context: TenantContext, warehouse_id: UUID) -> Warehouse:
        warehouse = await self.repository.get_warehouse(context.organization_id, warehouse_id)
        if warehouse is None:
            raise InventoryNotFound
        await self._ensure_location(context, warehouse.location_id)
        return warehouse

    async def _item(
        self,
        organization_id: UUID,
        item_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> InventoryItem:
        item = await self.repository.get_item(
            organization_id, item_id, include_inactive=include_inactive
        )
        if item is None:
            raise InventoryNotFound
        return item

    async def current_costs(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
    ) -> dict[UUID, Decimal]:
        await self._warehouse(context, warehouse_id)
        return await self.repository.get_current_costs(
            context.organization_id, warehouse_id, item_ids
        )

    async def ensure_warehouse_access(
        self, context: TenantContext, warehouse_id: UUID
    ) -> Warehouse:
        return await self._warehouse(context, warehouse_id)

    async def accessible_location_ids(self, context: TenantContext) -> tuple[UUID, ...]:
        return await self._accessible_location_ids(context)

    async def get_item_for_operation(
        self, organization_id: UUID, item_id: UUID, *, include_inactive: bool = False
    ) -> InventoryItem:
        return await self._item(organization_id, item_id, include_inactive=include_inactive)

    async def lock_operation_balances(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
        now: datetime,
    ) -> dict[UUID, StockBalance]:
        warehouse = await self._warehouse(context, warehouse_id)
        return await self.repository.lock_balances(
            context.organization_id,
            warehouse.location_id,
            warehouse.id,
            item_ids,
            now,
        )

    async def changed_items_since(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
        since: datetime,
    ) -> set[UUID]:
        await self._warehouse(context, warehouse_id)
        return await self.repository.changed_items_since(
            context.organization_id, warehouse_id, item_ids, since
        )

    async def lock_transfer_balances(
        self,
        context: TenantContext,
        source_warehouse_id: UUID,
        destination_warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
        now: datetime,
    ) -> dict[tuple[UUID, UUID], StockBalance]:
        source = await self._warehouse(context, source_warehouse_id)
        destination = await self._warehouse(context, destination_warehouse_id)
        pairs = tuple(
            (warehouse.location_id, warehouse.id, item_id)
            for warehouse in (source, destination)
            for item_id in item_ids
        )
        return await self.repository.lock_balances_across_warehouses(
            context.organization_id, pairs, now
        )

    async def _accessible_location_ids(self, context: TenantContext) -> tuple[UUID, ...]:
        locations = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(location.id for location in locations if location.is_active)

    async def _ensure_location(self, context: TenantContext, location_id: UUID) -> None:
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise InventoryNotFound from exc


def _name(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 150:
        raise ValueError("Name must contain between 1 and 150 characters")
    return normalized


def _sku(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if len(normalized) > 100:
        raise ValueError("SKU is too long")
    return normalized


def _note(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 1000:
        raise ValueError("Note is too long")
    return normalized


def _idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("Invalid idempotency key")
    return normalized


def _reference(value: str | None, reference_id: UUID | None) -> tuple[str | None, UUID | None]:
    if value is None and reference_id is None:
        return None, None
    if value is None or reference_id is None:
        raise ValueError("reference_type and reference_id must be supplied together")
    normalized = value.strip().upper()
    if normalized not in {
        "PURCHASE",
        "ORDER",
        "GOODS_RECEIPT",
        "INVENTORY_COUNT",
        "TRANSFER",
        "WRITE_OFF",
        "SUPPLIER_RETURN",
        "REFUND",
    }:
        raise ValueError("Unsupported inventory reference type")
    return normalized, reference_id


def _base_unit_cost(value: Decimal | None, unit) -> Decimal | None:
    if value is None:
        return None
    return _cost_amount(value / unit.base_factor)


def _cost_amount(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidInventoryUnit("Cost is outside NUMERIC(20, 6)") from exc
    if not result.is_finite() or result < 0 or result.adjusted() > 13:
        raise InvalidInventoryUnit("Cost is outside NUMERIC(20, 6)")
    return result
