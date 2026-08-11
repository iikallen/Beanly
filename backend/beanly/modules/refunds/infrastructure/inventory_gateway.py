from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.application.commands import CreateAndPostCommand, QuantityInput
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.refunds.application.ports import ReturnStockLine


class RefundInventoryGateway:
    def __init__(self, inventory: InventoryService) -> None:
        self.inventory = inventory

    async def stage_return(
        self,
        context: TenantContext,
        refund_id: UUID,
        warehouse_id: UUID,
        lines: tuple[ReturnStockLine, ...],
    ) -> tuple[UUID | None, Decimal, tuple[object, ...]]:
        if not lines:
            return None, Decimal(0), ()
        staged = await self.inventory.create_and_post_staged(
            context,
            CreateAndPostCommand(
                context.organization_id,
                context.user_id,
                warehouse_id,
                InventoryTransactionType.RETURN_IN,
                f"Refund {refund_id}",
                tuple(
                    QuantityInput(
                        line.inventory_item_id,
                        line.quantity,
                        UnitCode(line.base_unit),
                        unit_cost_amount=line.original_unit_cost,
                    )
                    for line in lines
                ),
                idempotency_key=f"refund:{refund_id}:inventory",
                reference_type="REFUND",
                reference_id=refund_id,
            ),
            validate_reference=False,
            allow_inactive_items=True,
        )
        cogs = sum(
            (line.total_cost_amount or Decimal(0) for line in staged.detail.lines), Decimal(0)
        )
        return staged.detail.transaction.id, cogs, staged.events
