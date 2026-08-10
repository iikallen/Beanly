from decimal import Decimal, InvalidOperation
from uuid import UUID

from beanly.core.observability import traced
from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    QuantityInput,
)
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.exceptions import InvalidInventoryOperation
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.payments.application.ports import (
    SaleStockLine,
    StagedSaleResult,
)
from beanly.modules.sales.domain.enums import SaleCostStatus
from beanly.modules.sales.domain.repositories import SalesRepository


class SalesOrderReferenceValidator:
    def __init__(self, repository: SalesRepository) -> None:
        self.repository = repository

    async def validate(
        self, organization_id: UUID, reference_type: str, reference_id: UUID
    ) -> None:
        if reference_type != "ORDER":
            raise InvalidInventoryOperation("Unsupported sales reference")
        if await self.repository.get_order(organization_id, reference_id) is None:
            raise InvalidInventoryOperation("Sales order reference was not found")


class InventorySaleGateway:
    def __init__(self, inventory: InventoryService) -> None:
        self.inventory = inventory

    async def stage_sale(
        self,
        context: TenantContext,
        *,
        order_id: UUID,
        order_number: int,
        warehouse_id: UUID,
        lines: tuple[SaleStockLine, ...],
    ) -> StagedSaleResult:
        if not lines:
            return StagedSaleResult(
                None, Decimal(0), SaleCostStatus.COMPLETE, (), ()
            )
        if any(line.quantity <= 0 for line in lines):
            raise InvalidInventoryOperation("Sale quantities must be positive")
        item_ids = tuple(line.inventory_item_id for line in lines)
        existing_costs = await self.inventory.current_costs(
            context, warehouse_id, item_ids
        )
        missing = tuple(sorted(set(item_ids) - existing_costs.keys(), key=str))
        staged = await self.inventory.create_and_post_staged(
            context,
            CreateAndPostCommand(
                context.organization_id,
                context.user_id,
                warehouse_id,
                InventoryTransactionType.SALE,
                f"Sale order #{order_number}",
                tuple(
                    QuantityInput(
                        line.inventory_item_id,
                        -line.quantity,
                        line.base_unit,
                    )
                    for line in lines
                ),
                f"sale:order:{order_id}",
                "ORDER",
                order_id,
            ),
        )
        if any(line.total_cost_amount is None for line in staged.detail.lines):
            raise InvalidInventoryOperation("Posted SALE cost snapshot is missing")
        with traced("cogs.calculate", order_id=str(order_id)):
            try:
                cogs_amount = -sum(
                    (line.total_cost_amount for line in staged.detail.lines),
                    Decimal(0),
                )
                cogs_amount = cogs_amount.quantize(Decimal("0.000001"))
            except (InvalidOperation, ValueError) as exc:
                raise InvalidInventoryOperation("COGS is outside NUMERIC(20, 6)") from exc
        if (
            not cogs_amount.is_finite()
            or cogs_amount < 0
            or (cogs_amount and cogs_amount.adjusted() > 13)
        ):
            raise InvalidInventoryOperation("COGS is outside NUMERIC(20, 6)")
        return StagedSaleResult(
            staged.detail.transaction.id,
            cogs_amount,
            SaleCostStatus.INCOMPLETE if missing else SaleCostStatus.COMPLETE,
            missing,
            staged.events,
        )
