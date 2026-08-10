from uuid import UUID

from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    QuantityInput,
)
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.exceptions import InvalidInventoryOperation
from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.purchasing.application.ports import (
    InventoryItemSnapshot,
    InventoryResources,
    PurchaseStockLine,
    ReturnStockLine,
    StagedInventoryResult,
)
from beanly.modules.purchasing.domain.repositories import PurchasingRepository


class PurchasingReferenceValidator:
    def __init__(self, repository: PurchasingRepository) -> None:
        self.repository = repository

    async def validate(
        self, organization_id: UUID, reference_type: str, reference_id: UUID
    ) -> None:
        if reference_type == "GOODS_RECEIPT":
            exists = await self.repository.get_receipt(organization_id, reference_id)
        elif reference_type == "SUPPLIER_RETURN":
            exists = await self.repository.get_return(organization_id, reference_id)
        else:
            raise InvalidInventoryOperation("Unsupported purchasing reference")
        if exists is None:
            raise InvalidInventoryOperation("Purchasing reference was not found")


class InventoryApplicationGateway:
    def __init__(self, inventory: InventoryService) -> None:
        self.inventory = inventory

    async def validate_resources(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
    ) -> InventoryResources:
        warehouse, items = await self.inventory.validate_purchase_resources(
            context, warehouse_id, item_ids
        )
        return InventoryResources(
            warehouse.id,
            warehouse.location_id,
            {item.id: InventoryItemSnapshot(item.id, item.base_unit.value) for item in items},
        )

    async def receive_purchase(
        self,
        context: TenantContext,
        receipt_id: UUID,
        warehouse_id: UUID,
        note: str,
        lines: tuple[PurchaseStockLine, ...],
    ) -> StagedInventoryResult:
        staged = await self.inventory.create_and_post_staged(
            context,
            CreateAndPostCommand(
                context.organization_id,
                context.user_id,
                warehouse_id,
                InventoryTransactionType.PURCHASE,
                note,
                tuple(
                    QuantityInput(
                        line.inventory_item_id,
                        line.base_quantity,
                        UnitCode(line.base_unit),
                        total_cost_amount=line.total_cost_amount,
                    )
                    for line in lines
                ),
                f"goods-receipt:{receipt_id}",
                "GOODS_RECEIPT",
                receipt_id,
            ),
        )
        return StagedInventoryResult(staged.detail.transaction.id, staged.events)

    async def reverse_purchase(
        self,
        context: TenantContext,
        transaction_id: UUID,
        receipt_id: UUID,
    ) -> StagedInventoryResult:
        staged = await self.inventory.reverse_staged(
            context,
            transaction_id,
            f"goods-receipt:{receipt_id}:reverse",
            allow_source_controlled=True,
        )
        return StagedInventoryResult(staged.detail.transaction.id, staged.events)

    async def return_to_supplier(
        self,
        context: TenantContext,
        supplier_return_id: UUID,
        warehouse_id: UUID,
        note: str,
        lines: tuple[ReturnStockLine, ...],
    ) -> StagedInventoryResult:
        staged = await self.inventory.create_and_post_staged(
            context,
            CreateAndPostCommand(
                context.organization_id,
                context.user_id,
                warehouse_id,
                InventoryTransactionType.RETURN_OUT,
                note,
                tuple(
                    QuantityInput(
                        line.inventory_item_id,
                        -line.base_quantity,
                        UnitCode(line.base_unit),
                    )
                    for line in lines
                ),
                f"supplier-return:{supplier_return_id}",
                "SUPPLIER_RETURN",
                supplier_return_id,
            ),
        )
        return StagedInventoryResult(staged.detail.transaction.id, staged.events)

    async def reverse_supplier_return(
        self,
        context: TenantContext,
        transaction_id: UUID,
        supplier_return_id: UUID,
    ) -> StagedInventoryResult:
        staged = await self.inventory.reverse_staged(
            context,
            transaction_id,
            f"supplier-return:{supplier_return_id}:reverse",
            allow_source_controlled=True,
        )
        return StagedInventoryResult(staged.detail.transaction.id, staged.events)
