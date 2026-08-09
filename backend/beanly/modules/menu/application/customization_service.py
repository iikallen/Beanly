from decimal import Decimal
from uuid import UUID

from beanly.modules.menu.application.ports import InventoryCostPort
from beanly.modules.menu.application.services import _six
from beanly.modules.menu.domain.entities import CustomizationPreview, EffectiveComponent
from beanly.modules.menu.domain.enums import ProductStatus, RecipeCostStatus
from beanly.modules.menu.domain.exceptions import (
    InvalidMenuOperation,
    InvalidModifierRecipe,
    InvalidModifierSelection,
    MenuNotFound,
)
from beanly.modules.menu.domain.repositories import MenuRepository
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext


class CustomizationService:
    def __init__(
        self,
        repository: MenuRepository,
        inventory: InventoryCostPort,
        organizations: OrganizationService,
    ) -> None:
        self.repository = repository
        self.inventory = inventory
        self.organizations = organizations

    async def preview(
        self,
        context: TenantContext,
        variant_id: UUID,
        warehouse_id: UUID,
        location_id: UUID,
        selected_option_ids: tuple[UUID, ...],
    ) -> CustomizationPreview:
        if len(selected_option_ids) != len(set(selected_option_ids)):
            raise InvalidModifierSelection("Modifier options must be unique")

        variant = await self.repository.get_variant(context.organization_id, variant_id)
        if variant is None:
            raise MenuNotFound("Variant not found")
        product = await self.repository.get_product(context.organization_id, variant.product_id)
        if (
            product is None
            or product.status != ProductStatus.ACTIVE
            or variant.status != ProductStatus.ACTIVE
        ):
            raise InvalidModifierSelection("Product variant is not active")

        warehouse = await self.inventory.get_warehouse_context(
            context.organization_id, warehouse_id
        )
        if warehouse is None:
            raise MenuNotFound("Warehouse not found")
        if warehouse.location_id != location_id:
            raise InvalidMenuOperation("Warehouse does not belong to the requested location")
        await self.organizations.ensure_location_access(context, location_id)

        groups = await self.repository.list_modifier_groups(
            context.organization_id, variant_id, location_id, True
        )
        options = {
            option.id: option for group in groups for option in group.options if option.is_active
        }
        selected = []
        for option_id in selected_option_ids:
            option = options.get(option_id)
            if option is None:
                raise InvalidModifierSelection(
                    "Modifier option does not belong to the active variant"
                )
            if not option.is_available:
                raise InvalidModifierSelection("Modifier option is unavailable at this location")
            selected.append(option)

        selected_set = set(selected_option_ids)
        for group in groups:
            count = sum(option.id in selected_set for option in group.options)
            if count < group.min_selections or count > group.max_selections:
                raise InvalidModifierSelection(
                    f"Modifier group '{group.name}' requires between "
                    f"{group.min_selections} and {group.max_selections} selections"
                )

        recipe = await self.repository.get_recipe(context.organization_id, variant_id)
        if recipe is None or not recipe.is_active:
            raise MenuNotFound("Recipe not found")
        base_quantities = {
            component.inventory_item_id: component.quantity for component in recipe.components
        }
        quantities = dict(base_quantities)
        for option in selected:
            for component in option.components:
                quantities[component.inventory_item_id] = (
                    quantities.get(component.inventory_item_id, Decimal(0))
                    + component.quantity_delta
                )
        if any(quantity < 0 for quantity in quantities.values()):
            raise InvalidModifierRecipe(
                "Modifier selection produces a negative ingredient quantity"
            )

        item_ids = tuple(quantities)
        items = await self.inventory.get_items(context.organization_id, item_ids)
        if set(items) != set(item_ids):
            raise MenuNotFound("Modifier recipe contains an unavailable inventory item")
        costs = await self.inventory.get_current_costs(
            context.organization_id, warehouse_id, item_ids
        )
        missing = tuple(items[item_id].name for item_id in item_ids if item_id not in costs)
        effective_components = tuple(
            EffectiveComponent(
                item_id,
                items[item_id].name,
                quantity,
                items[item_id].base_unit,
                costs.get(item_id),
                _six(quantity * costs[item_id]) if item_id in costs else None,
            )
            for item_id, quantity in quantities.items()
        )

        base_price = await self.repository.get_effective_price(
            context.organization_id, variant_id, location_id
        )
        if base_price is None:
            raise MenuNotFound("Variant not found")
        modifier_price = sum(
            option.effective_price_delta_minor
            if option.effective_price_delta_minor is not None
            else option.base_price_delta_minor
            for option in selected
        )
        final_price = base_price + modifier_price
        if final_price > 9223372036854775807:
            raise ValueError("Final price is outside BIGINT")

        if missing:
            return CustomizationPreview(
                variant_id,
                selected_option_ids,
                base_price,
                modifier_price,
                final_price,
                None,
                None,
                None,
                None,
                None,
                None,
                RecipeCostStatus.INCOMPLETE,
                missing,
                effective_components,
            )

        base_cost = _six(
            sum(
                (quantity * costs[item_id] for item_id, quantity in base_quantities.items()),
                Decimal(0),
            )
        )
        final_cost = _six(
            sum(
                (quantity * costs[item_id] for item_id, quantity in quantities.items()),
                Decimal(0),
            )
        )
        modifier_cost = _six(final_cost - base_cost)
        price = Decimal(final_price) / Decimal(100)
        gross_profit = _six(price - final_cost)
        food_cost = gross_margin = None
        if price:
            food_cost = _six(final_cost / price * 100)
            gross_margin = _six(gross_profit / price * 100)
        return CustomizationPreview(
            variant_id,
            selected_option_ids,
            base_price,
            modifier_price,
            final_price,
            base_cost,
            modifier_cost,
            final_cost,
            food_cost,
            gross_profit,
            gross_margin,
            RecipeCostStatus.COMPLETE,
            (),
            effective_components,
        )
