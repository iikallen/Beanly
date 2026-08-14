from uuid import UUID

from beanly.modules.menu.application.customization_service import CustomizationService
from beanly.modules.menu.domain.exceptions import (
    InvalidMenuOperation,
    MenuNotFound,
)
from beanly.modules.menu.domain.exceptions import (
    InvalidModifierRecipe as MenuInvalidModifierRecipe,
)
from beanly.modules.menu.domain.exceptions import (
    InvalidModifierSelection as MenuInvalidModifierSelection,
)
from beanly.modules.menu.domain.repositories import MenuRepository
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.application.ports import (
    SellableComponentSnapshot,
    SellableItemSnapshot,
    SellableModifierSnapshot,
)
from beanly.modules.sales.domain.exceptions import (
    InvalidModifierRecipe,
    InvalidModifierSelection,
    InvalidSalesOperation,
    ProductUnavailable,
    SalesNotFound,
)


class MenuSalesGateway:
    def __init__(self, repository: MenuRepository, customization: CustomizationService) -> None:
        self.repository = repository
        self.customization = customization

    async def resolve_order_item(
        self,
        context: TenantContext,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        location_id: UUID,
        selected_option_ids: tuple[UUID, ...],
    ) -> SellableItemSnapshot:
        try:
            variant = await self.repository.get_variant(context.organization_id, variant_id)
            if variant is None:
                raise SalesNotFound("Variant not found")
            product = await self.repository.get_product(context.organization_id, variant.product_id)
            if product is None:
                raise SalesNotFound("Product not found")
            location = await self.repository.get_product_location(
                context.organization_id, product.id, location_id
            )
            if location is not None and not location.is_available:
                raise ProductUnavailable("Product is unavailable at this location")
            groups = await self.repository.list_modifier_groups(
                context.organization_id, variant_id, location_id, True
            )
            preview = await self.customization.preview(
                context,
                variant_id,
                warehouse_id,
                location_id,
                selected_option_ids,
            )
        except MenuInvalidModifierSelection as exc:
            raise InvalidModifierSelection(str(exc)) from exc
        except MenuInvalidModifierRecipe as exc:
            raise InvalidModifierRecipe(str(exc)) from exc
        except MenuNotFound as exc:
            raise SalesNotFound(str(exc)) from exc
        except InvalidMenuOperation as exc:
            raise InvalidSalesOperation(str(exc)) from exc

        selected = set(selected_option_ids)
        modifiers = tuple(
            SellableModifierSnapshot(
                group.id,
                group.name,
                option.id,
                option.name,
                (
                    option.effective_price_delta_minor
                    if option.effective_price_delta_minor is not None
                    else option.base_price_delta_minor
                ),
                index,
            )
            for index, (group, option) in enumerate(
                (group, option)
                for group in groups
                for option in group.options
                if option.id in selected
            )
        )
        return SellableItemSnapshot(
            product.id,
            product.name,
            variant.id,
            variant.name,
            preview.base_price_minor,
            preview.modifier_price_minor,
            preview.final_price_minor,
            modifiers,
            tuple(
                SellableComponentSnapshot(
                    component.inventory_item_id,
                    component.name,
                    component.base_unit,
                    component.quantity,
                )
                for component in preview.effective_components
                if component.quantity > 0
            ),
        )
