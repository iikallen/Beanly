import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from beanly.modules.inventory.domain.value_objects import to_base_quantity
from beanly.modules.menu.application.commands import RecipeComponentInput, VariantInput
from beanly.modules.menu.application.ports import (
    InventoryCostPort,
    MenuEventPublisher,
    NullMenuEventPublisher,
)
from beanly.modules.menu.domain.entities import (
    Category,
    ComponentCost,
    Product,
    ProductLocationSetting,
    ProductVariant,
    Recipe,
    RecipeComponent,
    RecipeComponentDetail,
    RecipeCost,
    RecipeDetail,
    VariantPrice,
)
from beanly.modules.menu.domain.enums import ProductStatus, RecipeCostStatus
from beanly.modules.menu.domain.events import (
    CategoryCreated,
    ProductArchived,
    ProductCreated,
    ProductUpdated,
    RecipeCostChanged,
    RecipeCreated,
    RecipeUpdated,
    VariantCreated,
    VariantPriceChanged,
)
from beanly.modules.menu.domain.exceptions import (
    InvalidMenuOperation,
    MenuConflict,
    MenuNotFound,
)
from beanly.modules.menu.domain.repositories import MenuRepository
from beanly.modules.menu.domain.value_objects import normalized_name, normalized_optional_text
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext

_SIX = Decimal("0.000001")
logger = logging.getLogger(__name__)


class MenuService:
    def __init__(
        self,
        repository: MenuRepository,
        inventory: InventoryCostPort,
        organizations: OrganizationService,
        publisher: MenuEventPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.inventory = inventory
        self.organizations = organizations
        self.publisher = publisher or NullMenuEventPublisher()

    async def create_category(self, context: TenantContext, name: str, sort_order: int) -> Category:
        now = datetime.now(UTC)
        value = Category(
            uuid4(),
            context.organization_id,
            normalized_name(name, 150),
            sort_order,
            True,
            now,
            now,
        )
        return await self._write(self.repository.add_category(value), (CategoryCreated(value.id),))

    async def list_categories(self, context: TenantContext) -> list[Category]:
        return await self.repository.list_categories(context.organization_id)

    async def update_category(
        self,
        context: TenantContext,
        category_id: UUID,
        *,
        name: str | None = None,
        sort_order: int | None = None,
        is_active: bool | None = None,
    ) -> Category:
        try:
            if not await self.repository.lock_category(context.organization_id, category_id):
                raise MenuNotFound("Category not found")
            value = await self._category(context.organization_id, category_id)
            updated = replace(
                value,
                name=normalized_name(name, 150) if name is not None else value.name,
                sort_order=sort_order if sort_order is not None else value.sort_order,
                is_active=is_active if is_active is not None else value.is_active,
                updated_at=datetime.now(UTC),
            )
            result = await self.repository.update_category(updated)
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def archive_category(self, context: TenantContext, category_id: UUID) -> Category:
        return await self.update_category(context, category_id, is_active=False)

    async def create_product(
        self,
        context: TenantContext,
        category_id: UUID,
        name: str,
        description: str | None,
        image_url: str | None,
        default_variant: VariantInput,
    ) -> Product:
        now = datetime.now(UTC)
        product = Product(
            uuid4(),
            context.organization_id,
            category_id,
            normalized_name(name, 200),
            normalized_optional_text(description),
            normalized_optional_text(image_url),
            ProductStatus.DRAFT,
            now,
            now,
        )
        variant = self._new_variant(
            context.organization_id,
            product.id,
            default_variant,
            is_default=True,
            sort_order=0,
            now=now,
        )
        try:
            if not await self.repository.lock_category(context.organization_id, category_id):
                raise MenuNotFound("Category not found")
            await self._category(context.organization_id, category_id, active=True)
            await self.repository.add_product(product)
            await self.repository.add_variant(variant)
            await self.repository.commit()
            await self._publish((ProductCreated(product.id), VariantCreated(variant.id)))
        except Exception:
            await self.repository.rollback()
            raise
        return await self._product(context.organization_id, product.id)

    async def list_products(
        self,
        context: TenantContext,
        category_id: UUID | None,
        product_status: ProductStatus | None,
        search: str | None,
        location_id: UUID | None,
    ) -> list[Product]:
        if category_id is not None:
            await self._category(context.organization_id, category_id)
        if location_id is not None:
            await self.organizations.ensure_location_access(context, location_id)
        products = await self.repository.list_products(
            context.organization_id,
            category_id,
            product_status,
            normalized_optional_text(search),
            location_id,
        )
        return await self._with_effective_prices(products, location_id)

    async def get_product(
        self, context: TenantContext, product_id: UUID, location_id: UUID | None = None
    ) -> Product:
        product = await self._product(context.organization_id, product_id)
        if location_id is None:
            return product
        await self.organizations.ensure_location_access(context, location_id)
        setting = await self.repository.get_product_location(
            context.organization_id, product_id, location_id
        )
        product = replace(
            product,
            is_available=setting.is_available if setting else True,
            is_visible=setting.is_visible if setting else True,
        )
        return (await self._with_effective_prices([product], location_id))[0]

    async def update_product(
        self,
        context: TenantContext,
        product_id: UUID,
        *,
        category_id: UUID | None,
        name: str | None,
        description: str | None,
        description_set: bool,
        image_url: str | None,
        image_url_set: bool,
        status: ProductStatus | None,
    ) -> Product:
        if status == ProductStatus.ARCHIVED:
            raise InvalidMenuOperation("Use the product archive endpoint")
        try:
            if category_id is not None:
                if not await self.repository.lock_category(context.organization_id, category_id):
                    raise MenuNotFound("Category not found")
                await self._category(context.organization_id, category_id, active=True)
            if await self.repository.lock_product(context.organization_id, product_id) is None:
                raise MenuNotFound("Product not found")
            product = await self._product(context.organization_id, product_id)
            if product.status == ProductStatus.ARCHIVED:
                raise InvalidMenuOperation("Archived products cannot be updated")
            updated = replace(
                product,
                category_id=category_id or product.category_id,
                name=normalized_name(name, 200) if name is not None else product.name,
                description=(
                    normalized_optional_text(description)
                    if description_set
                    else product.description
                ),
                image_url=(
                    normalized_optional_text(image_url) if image_url_set else product.image_url
                ),
                status=status or product.status,
                updated_at=datetime.now(UTC),
            )
            result = await self.repository.update_product(updated)
            await self.repository.commit()
            await self._publish((ProductUpdated(product.id),))
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def archive_product(self, context: TenantContext, product_id: UUID) -> Product:
        try:
            if await self.repository.lock_product(context.organization_id, product_id) is None:
                raise MenuNotFound("Product not found")
            product = await self._product(context.organization_id, product_id)
            archived = await self.repository.update_product(
                replace(
                    product,
                    status=ProductStatus.ARCHIVED,
                    updated_at=datetime.now(UTC),
                )
            )
            await self.repository.commit()
            await self._publish((ProductArchived(product.id),))
            return archived
        except Exception:
            await self.repository.rollback()
            raise

    async def create_variant(
        self,
        context: TenantContext,
        product_id: UUID,
        value: VariantInput,
        is_default: bool,
        sort_order: int,
    ) -> ProductVariant:
        product = await self._product(context.organization_id, product_id)
        if product.status == ProductStatus.ARCHIVED:
            raise InvalidMenuOperation("Cannot add a variant to an archived product")
        now = datetime.now(UTC)
        variant = self._new_variant(
            context.organization_id,
            product_id,
            value,
            is_default=is_default,
            sort_order=sort_order,
            now=now,
        )
        try:
            locked_status = await self.repository.lock_product(context.organization_id, product_id)
            if locked_status is None:
                raise MenuNotFound("Product not found")
            if locked_status == ProductStatus.ARCHIVED:
                raise InvalidMenuOperation("Cannot add a variant to an archived product")
            if is_default:
                await self.repository.clear_default_variant(context.organization_id, product_id)
            created = await self.repository.add_variant(variant)
            await self.repository.commit()
            await self._publish((VariantCreated(created.id),))
            return created
        except Exception:
            await self.repository.rollback()
            raise

    async def update_variant(
        self,
        context: TenantContext,
        variant_id: UUID,
        *,
        name: str | None,
        sku: str | None,
        sku_set: bool,
        base_price_minor: int | None,
        is_default: bool | None,
        sort_order: int | None,
        status: ProductStatus | None,
    ) -> ProductVariant:
        variant = await self._variant(context.organization_id, variant_id)
        if base_price_minor is not None and not 0 <= base_price_minor <= 9223372036854775807:
            raise ValueError("Price must be non-negative")
        try:
            if (
                await self.repository.lock_product(context.organization_id, variant.product_id)
                is None
            ):
                raise MenuNotFound("Product not found")
            variant = await self._variant(context.organization_id, variant_id)
            if variant.status == ProductStatus.ARCHIVED:
                raise InvalidMenuOperation("Archived variants cannot be updated")
            if variant.is_default and is_default is False:
                raise InvalidMenuOperation("Promote another variant before clearing the default")
            updated = replace(
                variant,
                name=normalized_name(name, 100) if name is not None else variant.name,
                sku=normalized_optional_text(sku) if sku_set else variant.sku,
                base_price_minor=(
                    base_price_minor if base_price_minor is not None else variant.base_price_minor
                ),
                is_default=is_default if is_default is not None else variant.is_default,
                sort_order=sort_order if sort_order is not None else variant.sort_order,
                status=status or variant.status,
                updated_at=datetime.now(UTC),
            )
            if updated.status == ProductStatus.ARCHIVED:
                raise InvalidMenuOperation("Use the variant archive endpoint")
            if updated.is_default and not variant.is_default:
                await self.repository.clear_default_variant(
                    context.organization_id, variant.product_id
                )
            result = await self.repository.update_variant(updated)
            await self.repository.commit()
            if result.base_price_minor != variant.base_price_minor:
                await self._publish((VariantPriceChanged(result.id, None),))
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def archive_variant(self, context: TenantContext, variant_id: UUID) -> ProductVariant:
        variant = await self._variant(context.organization_id, variant_id)
        try:
            if (
                await self.repository.lock_product(context.organization_id, variant.product_id)
                is None
            ):
                raise MenuNotFound("Product not found")
            variant = await self._variant(context.organization_id, variant_id)
            if variant.status == ProductStatus.ARCHIVED:
                raise InvalidMenuOperation("Variant is already archived")
            replacement = await self.repository.first_active_variant(
                context.organization_id, variant.product_id, variant.id
            )
            if replacement is None:
                raise InvalidMenuOperation("A product must keep at least one active variant")
            archived = await self.repository.update_variant(
                replace(
                    variant,
                    status=ProductStatus.ARCHIVED,
                    is_default=False,
                    updated_at=datetime.now(UTC),
                )
            )
            if variant.is_default:
                await self.repository.update_variant(
                    replace(replacement, is_default=True, updated_at=datetime.now(UTC))
                )
            await self.repository.commit()
            return archived
        except Exception:
            await self.repository.rollback()
            raise

    async def set_recipe(
        self,
        context: TenantContext,
        variant_id: UUID,
        name: str | None,
        yield_quantity: Decimal,
        inputs: tuple[RecipeComponentInput, ...],
    ) -> RecipeDetail:
        variant = await self._variant(context.organization_id, variant_id)
        if variant.status == ProductStatus.ARCHIVED:
            raise InvalidMenuOperation("Cannot set a recipe on an archived variant")
        if yield_quantity != 1:
            raise InvalidMenuOperation("Stage 8 recipes must yield exactly 1")
        if not inputs:
            raise ValueError("Recipe requires at least one component")
        if any(not value.quantity.is_finite() or value.quantity <= 0 for value in inputs):
            raise ValueError("Recipe component quantity must be positive")
        item_ids = tuple(value.inventory_item_id for value in inputs)
        if len(set(item_ids)) != len(item_ids):
            raise MenuConflict("Recipe ingredients must be unique")
        items = await self.inventory.get_items(context.organization_id, item_ids)
        if set(items) != set(item_ids):
            raise MenuNotFound("Inventory item not found")

        current = await self.repository.get_recipe(context.organization_id, variant_id)
        now = datetime.now(UTC)
        recipe_id = current.id if current else uuid4()
        components = tuple(
            RecipeComponent(
                uuid4(),
                recipe_id,
                value.inventory_item_id,
                to_base_quantity(
                    value.quantity,
                    value.unit,
                    items[value.inventory_item_id].base_unit,
                ),
                value.sort_order,
                now,
                now,
            )
            for value in inputs
        )
        recipe = Recipe(
            recipe_id,
            context.organization_id,
            variant_id,
            normalized_name(name or variant.name, 200),
            yield_quantity,
            True,
            current.created_at if current else now,
            now,
            components,
        )
        try:
            saved, created = await self.repository.replace_recipe(recipe)
            await self.repository.commit()
            await self._publish(
                (
                    RecipeCreated(saved.id) if created else RecipeUpdated(saved.id),
                    RecipeCostChanged(saved.id),
                )
            )
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_recipe(context, variant_id)

    async def get_recipe(self, context: TenantContext, variant_id: UUID) -> RecipeDetail:
        await self._variant(context.organization_id, variant_id)
        recipe = await self.repository.get_recipe(context.organization_id, variant_id)
        if recipe is None:
            raise MenuNotFound("Recipe not found")
        item_ids = tuple(value.inventory_item_id for value in recipe.components)
        items = await self.inventory.get_items(context.organization_id, item_ids)
        if set(items) != set(item_ids):
            raise MenuNotFound("Recipe contains an unavailable inventory item")
        return RecipeDetail(
            recipe,
            tuple(
                RecipeComponentDetail(
                    value,
                    items[value.inventory_item_id].name,
                    items[value.inventory_item_id].base_unit,
                )
                for value in recipe.components
            ),
        )

    async def calculate_cost(
        self,
        context: TenantContext,
        variant_id: UUID,
        warehouse_id: UUID,
        location_id: UUID | None,
    ) -> RecipeCost:
        variant = await self._variant(context.organization_id, variant_id)
        warehouse = await self.inventory.get_warehouse_context(
            context.organization_id, warehouse_id
        )
        if warehouse is None:
            raise MenuNotFound("Warehouse not found")
        if location_id is not None and location_id != warehouse.location_id:
            raise InvalidMenuOperation("Warehouse does not belong to the requested location")
        await self.organizations.ensure_location_access(context, warehouse.location_id)
        recipe = await self.get_recipe(context, variant_id)
        item_ids = tuple(value.component.inventory_item_id for value in recipe.components)
        costs = await self.inventory.get_current_costs(
            context.organization_id, warehouse_id, item_ids
        )
        components = tuple(
            ComponentCost(
                value.component.inventory_item_id,
                value.item_name,
                value.component.quantity,
                value.base_unit,
                costs.get(value.component.inventory_item_id),
                (
                    _six(value.component.quantity * costs[value.component.inventory_item_id])
                    if value.component.inventory_item_id in costs
                    else None
                ),
            )
            for value in recipe.components
        )
        price_minor = await self.repository.get_effective_price(
            context.organization_id, variant.id, warehouse.location_id
        )
        if price_minor is None:
            raise MenuNotFound("Variant not found")
        return _cost_result(variant.id, price_minor, components)

    async def calculate_costs(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        location_id: UUID | None = None,
    ) -> tuple[RecipeCost, ...]:
        warehouse = await self.inventory.get_warehouse_context(
            context.organization_id, warehouse_id
        )
        if warehouse is None:
            raise MenuNotFound("Warehouse not found")
        if location_id is not None and location_id != warehouse.location_id:
            raise InvalidMenuOperation("Warehouse does not belong to the requested location")
        await self.organizations.ensure_location_access(context, warehouse.location_id)
        products = await self.repository.list_products(
            context.organization_id, None, ProductStatus.ACTIVE, None, None
        )
        variants = tuple(
            variant
            for product in products
            for variant in product.variants
            if variant.status == ProductStatus.ACTIVE
        )
        variant_ids = tuple(value.id for value in variants)
        recipes = await self.repository.list_recipes(context.organization_id, variant_ids)
        item_ids = tuple(
            dict.fromkeys(
                component.inventory_item_id
                for recipe in recipes.values()
                for component in recipe.components
            )
        )
        items = await self.inventory.get_items(context.organization_id, item_ids)
        # The whole screen crosses the InventoryCostPort exactly once.
        costs = await self.inventory.get_current_costs(
            context.organization_id, warehouse_id, item_ids
        )
        prices = await self.repository.get_effective_prices(
            context.organization_id, variant_ids, warehouse.location_id
        )
        results: list[RecipeCost] = []
        for variant in variants:
            recipe = recipes.get(variant.id)
            if recipe is None:
                results.append(
                    RecipeCost(
                        variant.id,
                        prices[variant.id],
                        None,
                        None,
                        None,
                        None,
                        RecipeCostStatus.INCOMPLETE,
                        ("Recipe not configured",),
                        (),
                    )
                )
                continue
            unavailable = tuple(
                component.inventory_item_id
                for component in recipe.components
                if component.inventory_item_id not in items
            )
            if unavailable:
                results.append(
                    RecipeCost(
                        variant.id,
                        prices[variant.id],
                        None,
                        None,
                        None,
                        None,
                        RecipeCostStatus.INCOMPLETE,
                        tuple(f"Unavailable inventory item: {item_id}" for item_id in unavailable),
                        (),
                    )
                )
                continue
            component_costs = tuple(
                ComponentCost(
                    component.inventory_item_id,
                    items[component.inventory_item_id].name,
                    component.quantity,
                    items[component.inventory_item_id].base_unit,
                    costs.get(component.inventory_item_id),
                    (
                        _six(component.quantity * costs[component.inventory_item_id])
                        if component.inventory_item_id in costs
                        else None
                    ),
                )
                for component in recipe.components
            )
            results.append(_cost_result(variant.id, prices[variant.id], component_costs))
        return tuple(results)

    async def set_variant_price(
        self,
        context: TenantContext,
        variant_id: UUID,
        location_id: UUID,
        price_minor: int | None,
    ) -> VariantPrice | None:
        await self._variant(context.organization_id, variant_id)
        await self.organizations.ensure_location_access(context, location_id)
        if price_minor is not None and not 0 <= price_minor <= 9223372036854775807:
            raise ValueError("Price must be non-negative")
        if price_minor is None:
            try:
                await self.repository.delete_variant_price(
                    context.organization_id, variant_id, location_id
                )
                await self.repository.commit()
                await self._publish((VariantPriceChanged(variant_id, location_id),))
                return None
            except Exception:
                await self.repository.rollback()
                raise
        now = datetime.now(UTC)
        return await self._write(
            self.repository.set_variant_price(
                VariantPrice(
                    uuid4(),
                    context.organization_id,
                    location_id,
                    variant_id,
                    price_minor,
                    now,
                    now,
                )
            ),
            (VariantPriceChanged(variant_id, location_id),),
        )

    async def set_product_location(
        self,
        context: TenantContext,
        product_id: UUID,
        location_id: UUID,
        is_available: bool,
        is_visible: bool,
    ) -> ProductLocationSetting:
        await self._product(context.organization_id, product_id)
        await self.organizations.ensure_location_access(context, location_id)
        now = datetime.now(UTC)
        return await self._write(
            self.repository.set_product_location(
                ProductLocationSetting(
                    uuid4(),
                    context.organization_id,
                    location_id,
                    product_id,
                    is_available,
                    is_visible,
                    now,
                    now,
                )
            )
        )

    async def get_menu(self, context: TenantContext, location_id: UUID) -> list[Product]:
        await self.organizations.ensure_location_access(context, location_id)
        products = await self.repository.list_products(
            context.organization_id,
            None,
            ProductStatus.ACTIVE,
            None,
            location_id,
        )
        active_products = []
        for product in products:
            if product.is_available is not True or product.is_visible is not True:
                continue
            projected = replace(
                product,
                variants=tuple(
                    variant
                    for variant in product.variants
                    if variant.status == ProductStatus.ACTIVE
                ),
            )
            if projected.variants:
                active_products.append(projected)
        return await self._with_effective_prices(active_products, location_id)

    async def _with_effective_prices(
        self, products: list[Product], location_id: UUID | None
    ) -> list[Product]:
        if location_id is None:
            return products
        variant_ids = tuple(variant.id for product in products for variant in product.variants)
        if not products:
            return products
        organization_id = products[0].organization_id
        prices = await self.repository.get_effective_prices(
            organization_id,
            variant_ids,
            location_id,
        )
        overrides = await self.repository.get_location_prices(
            organization_id, variant_ids, location_id
        )
        return [
            replace(
                product,
                variants=tuple(
                    replace(
                        variant,
                        location_price_minor=overrides.get(variant.id),
                        effective_price_minor=prices[variant.id],
                    )
                    for variant in product.variants
                ),
            )
            for product in products
        ]

    async def _category(
        self, organization_id: UUID, category_id: UUID, *, active: bool = False
    ) -> Category:
        value = await self.repository.get_category(organization_id, category_id)
        if value is None or (active and not value.is_active):
            raise MenuNotFound("Category not found")
        return value

    async def _product(self, organization_id: UUID, product_id: UUID) -> Product:
        value = await self.repository.get_product(organization_id, product_id)
        if value is None:
            raise MenuNotFound("Product not found")
        return value

    async def _variant(self, organization_id: UUID, variant_id: UUID) -> ProductVariant:
        value = await self.repository.get_variant(organization_id, variant_id)
        if value is None:
            raise MenuNotFound("Variant not found")
        return value

    async def _write(self, operation, events: tuple[object, ...] = ()):
        try:
            result = await operation
            await self.repository.commit()
            await self._publish(events)
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def _publish(self, events: tuple[object, ...]) -> None:
        for event in events:
            try:
                await self.publisher.publish(event)
            except Exception:
                # State is committed; event transport is best-effort until an outbox exists.
                logger.exception(
                    "Menu domain event publish failed",
                    extra={"event_type": type(event).__name__},
                )

    @staticmethod
    def _new_variant(
        organization_id: UUID,
        product_id: UUID,
        value: VariantInput,
        *,
        is_default: bool,
        sort_order: int,
        now: datetime,
    ) -> ProductVariant:
        if not 0 <= value.base_price_minor <= 9223372036854775807:
            raise ValueError("Price must be non-negative")
        return ProductVariant(
            uuid4(),
            organization_id,
            product_id,
            normalized_name(value.name, 100),
            normalized_optional_text(value.sku),
            value.base_price_minor,
            is_default,
            ProductStatus.ACTIVE,
            sort_order,
            now,
            now,
        )


def _six(value: Decimal) -> Decimal:
    return value.quantize(_SIX, rounding=ROUND_HALF_UP)


def _cost_result(
    variant_id: UUID, price_minor: int, components: tuple[ComponentCost, ...]
) -> RecipeCost:
    missing = tuple(value.name for value in components if value.unit_cost is None)
    if missing:
        return RecipeCost(
            variant_id,
            price_minor,
            None,
            None,
            None,
            None,
            RecipeCostStatus.INCOMPLETE,
            missing,
            components,
        )
    recipe_cost = _six(sum((value.cost or Decimal(0) for value in components), Decimal(0)))
    price = Decimal(price_minor) / Decimal(100)
    gross_profit = _six(price - recipe_cost)
    if price == 0:
        food_cost = gross_margin = None
    else:
        food_cost = _six(recipe_cost / price * 100)
        gross_margin = _six(gross_profit / price * 100)
    return RecipeCost(
        variant_id,
        price_minor,
        recipe_cost,
        food_cost,
        gross_profit,
        gross_margin,
        RecipeCostStatus.COMPLETE,
        (),
        components,
    )
