from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.events import DomainEventSink
from beanly.core.money import MAX_BIGINT, MAX_NUMERIC_20_6_MINOR
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.inventory.application.commands import CreateAndPostCommand, QuantityInput
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.entities import InventoryItem
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.value_objects import UnitCode, to_base_quantity
from beanly.modules.inventory.infrastructure.db.models import InventoryItemModel, WarehouseModel
from beanly.modules.inventory.infrastructure.db.repositories import SqlAlchemyInventoryRepository
from beanly.modules.menu.domain.entities import (
    Category,
    ModifierGroup,
    ModifierOption,
    ModifierOptionComponent,
    Product,
    ProductLocationSetting,
    ProductVariant,
    Recipe,
    RecipeComponent,
    VariantPrice,
)
from beanly.modules.menu.domain.enums import ModifierSelectionType, ProductStatus
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ModifierGroupModel,
    ModifierOptionModel,
    ProductModel,
    ProductVariantModel,
    RecipeModel,
    VariantPriceModel,
)
from beanly.modules.menu.infrastructure.db.repositories import SqlAlchemyMenuRepository
from beanly.modules.onboarding.domain.entities import ImportEntity, ImportRun
from beanly.modules.onboarding.domain.enums import (
    ImportEntityType,
    ImportResolution,
    ImportSourceType,
)
from beanly.modules.onboarding.domain.exceptions import (
    ImportLocationNotFound,
    ImportValidationFailed,
)
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.infrastructure.db.models import LocationModel


class SqlAlchemyImportApplyGateway:
    def __init__(
        self,
        session: AsyncSession,
        inventory: InventoryService,
        organizations: OrganizationService,
        sink: DomainEventSink,
        audit: SecurityAuditRecorder | None = None,
    ) -> None:
        self.session = session
        self.inventory = inventory
        self.organizations = organizations
        self.sink = sink
        self.audit = audit
        self.menu_repository = SqlAlchemyMenuRepository(session)
        self.inventory_repository = SqlAlchemyInventoryRepository(session)

    async def ensure_location_access(self, context: TenantContext, location_id: UUID) -> None:
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise ImportLocationNotFound("Location is unavailable") from exc

    async def accessible_location_ids(self, context: TenantContext) -> tuple[UUID, ...]:
        return tuple(
            value.id
            for value in await self.organizations.list_locations(
                ListLocationsQuery(context.user_id, context.organization_id)
            )
            if value.is_active
        )

    async def apply(self, context: TenantContext, run: ImportRun) -> None:
        await self._assert_location(context.organization_id, run.location_id)
        now = datetime.now(UTC)
        targets: dict[str, UUID] = {}
        opening: list[ImportEntity] = []
        dependency_order = {
            ImportEntityType.CATEGORY: 0,
            ImportEntityType.INVENTORY_ITEM: 0,
            ImportEntityType.PRODUCT: 1,
            ImportEntityType.VARIANT: 2,
            ImportEntityType.LOCATION_PRICE: 3,
            ImportEntityType.RECIPE: 4,
            ImportEntityType.MODIFIER_GROUP: 4,
            ImportEntityType.MODIFIER_OPTION: 5,
            ImportEntityType.OPENING_BALANCE: 6,
        }
        for entity in sorted(
            run.entities,
            key=lambda value: (
                dependency_order[value.entity_type],
                value.sort_order,
                str(value.id),
            ),
        ):
            if entity.resolution is ImportResolution.SKIP:
                continue
            if entity.resolution is ImportResolution.MATCH_EXISTING:
                if entity.target_id is None or not await self._target_owned(context, entity):
                    raise ImportValidationFailed("MATCH_EXISTING target is outside the tenant")
                targets[entity.source_key] = entity.target_id
                continue
            if entity.entity_type is ImportEntityType.CATEGORY:
                target, _created = await self._category(context, entity, now)
            elif entity.entity_type is ImportEntityType.INVENTORY_ITEM:
                target = await self._inventory_item(context, entity, now)
            elif entity.entity_type is ImportEntityType.PRODUCT:
                category_id = _reference(targets, entity, "category_key")
                target = uuid4()
                await self.menu_repository.add_product(
                    Product(
                        target,
                        context.organization_id,
                        category_id,
                        _name(entity.payload, "name", 200),
                        _optional_text(entity.payload.get("description"), 10_000),
                        None,
                        ProductStatus.DRAFT,
                        now,
                        now,
                    )
                )
            elif entity.entity_type is ImportEntityType.VARIANT:
                product_id = _reference(targets, entity, "product_key")
                target = uuid4()
                await self.menu_repository.add_variant(
                    ProductVariant(
                        target,
                        context.organization_id,
                        product_id,
                        _name(entity.payload, "name", 100),
                        _optional_text(entity.payload.get("sku"), 100),
                        _minor(entity.payload, "price_minor"),
                        bool(entity.payload.get("is_default", True)),
                        ProductStatus.DRAFT,
                        int(entity.payload.get("sort_order", 0)),
                        now,
                        now,
                    )
                )
            elif entity.entity_type is ImportEntityType.LOCATION_PRICE:
                variant_id = _reference(targets, entity, "variant_key")
                location = await self.session.scalar(
                    select(LocationModel).where(
                        LocationModel.organization_id == context.organization_id,
                        LocationModel.id == run.location_id,
                    )
                )
                expected_name = str(entity.payload.get("location_name", "")).strip()
                if location is None or (
                    expected_name and expected_name.casefold() != location.name.casefold()
                ):
                    raise ImportValidationFailed("LOCATION_NAME_MISMATCH")
                target = uuid4()
                await self.menu_repository.set_variant_price(
                    VariantPrice(
                        target,
                        context.organization_id,
                        run.location_id,
                        variant_id,
                        _minor(entity.payload, "price_minor"),
                        now,
                        now,
                    )
                )
                product_id = await self.session.scalar(
                    select(ProductVariantModel.product_id).where(
                        ProductVariantModel.organization_id == context.organization_id,
                        ProductVariantModel.id == variant_id,
                    )
                )
                if product_id is None:
                    raise ImportValidationFailed("Variant disappeared")
                await self.menu_repository.set_product_location(
                    ProductLocationSetting(
                        uuid4(),
                        context.organization_id,
                        run.location_id,
                        product_id,
                        bool(entity.payload.get("available", True)),
                        True,
                        now,
                        now,
                    )
                )
            elif entity.entity_type is ImportEntityType.RECIPE:
                target = await self._recipe(context, entity, targets, now)
            elif entity.entity_type is ImportEntityType.MODIFIER_GROUP:
                target = uuid4()
                await self.menu_repository.add_modifier_group(
                    ModifierGroup(
                        target,
                        context.organization_id,
                        _reference(targets, entity, "variant_key"),
                        _name(entity.payload, "name", 150),
                        ModifierSelectionType(str(entity.payload.get("selection_type", "SINGLE"))),
                        int(entity.payload.get("min_selections", 0)),
                        int(entity.payload.get("max_selections", 1)),
                        int(entity.payload.get("sort_order", 0)),
                        True,
                        now,
                        now,
                    )
                )
            elif entity.entity_type is ImportEntityType.MODIFIER_OPTION:
                target = uuid4()
                components = await self._modifier_components(entity, targets, target, now)
                option = ModifierOption(
                    target,
                    context.organization_id,
                    _reference(targets, entity, "group_key"),
                    _name(entity.payload, "name", 150),
                    _minor(entity.payload, "price_delta_minor"),
                    bool(entity.payload.get("is_default", False)),
                    int(entity.payload.get("sort_order", 0)),
                    True,
                    now,
                    now,
                    components,
                )
                await self.menu_repository.add_modifier_option(option)
                if components:
                    await self.menu_repository.replace_modifier_components(option)
            elif entity.entity_type is ImportEntityType.OPENING_BALANCE:
                opening.append(entity)
                continue
            else:
                raise ImportValidationFailed("Unsupported canonical entity")
            await self.session.flush()
            entity.target_id = target
            targets[entity.source_key] = target
        if opening:
            await self._opening_balance(context, run, opening, targets)
        if self.audit:
            action = (
                "ONBOARDING_TEMPLATE_APPLIED"
                if run.source_type is ImportSourceType.BEANLY_TEMPLATE
                else "POSTER_IMPORT_APPLIED"
                if run.source_type is ImportSourceType.POSTER_EXPORT
                else "MENU_IMPORT_APPLIED"
            )
            await self.audit.record(
                action=action,
                resource_type="onboarding_import_run",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=run.id,
                metadata={
                    "import_run_id": str(run.id),
                    "source_type": run.source_type.value,
                    "entities_created": sum(
                        value.resolution is ImportResolution.CREATE for value in run.entities
                    ),
                    "entities_matched": sum(
                        value.resolution is ImportResolution.MATCH_EXISTING
                        for value in run.entities
                    ),
                    "entities_skipped": sum(
                        value.resolution is ImportResolution.SKIP for value in run.entities
                    ),
                },
            )

    async def activate_ready(
        self,
        context: TenantContext,
        run: ImportRun,
        product_ids: tuple[UUID, ...],
        *,
        confirm_starter_recipes_reviewed: bool,
    ) -> tuple[list[dict[str, object]], int]:
        imported_products = {
            entity.target_id: entity
            for entity in run.entities
            if entity.entity_type is ImportEntityType.PRODUCT and entity.target_id is not None
        }
        requested = tuple(dict.fromkeys(product_ids))
        if any(product_id not in imported_products for product_id in requested):
            raise ImportValidationFailed("Product does not belong to the applied import")
        variant_products = {
            entity.source_key: str(entity.payload.get("product_key", ""))
            for entity in run.entities
            if entity.entity_type is ImportEntityType.VARIANT
        }
        reviewed_required = {
            variant_products.get(str(entity.payload.get("variant_key", "")), "")
            for entity in run.entities
            if entity.entity_type is ImportEntityType.RECIPE
            and "DRAFT_RECIPE_REVIEW_REQUIRED" in entity.warning_codes
        }
        source_to_target = {
            entity.source_key: entity.target_id for entity in run.entities if entity.target_id
        }
        items: list[dict[str, object]] = []
        activate: list[UUID] = []
        for product_id in requested:
            product_entity = imported_products[product_id]
            reasons: list[str] = []
            variants = [
                entity
                for entity in run.entities
                if entity.entity_type is ImportEntityType.VARIANT
                and entity.payload.get("product_key") == product_entity.source_key
                and entity.target_id is not None
            ]
            if not variants:
                reasons.append("VARIANT_REQUIRED")
            variant_ids = tuple(value.target_id for value in variants if value.target_id)
            if variant_ids:
                prices = await self.menu_repository.get_effective_prices(
                    context.organization_id, variant_ids, run.location_id
                )
                if any(prices.get(value, 0) <= 0 for value in variant_ids):
                    reasons.append("PRICE_REQUIRED")
            recipe_variants = {
                _reference_from_payload(entity.payload, "variant_key")
                for entity in run.entities
                if entity.entity_type is ImportEntityType.RECIPE
                and entity.resolution is not ImportResolution.SKIP
            }
            if any(
                value.source_key in recipe_variants
                and not entity_has_valid_recipe(run, value.source_key)
                for value in variants
            ):
                reasons.append("VALID_RECIPE_REQUIRED")
            if (
                product_entity.source_key in reviewed_required
                and not confirm_starter_recipes_reviewed
            ):
                reasons.append("STARTER_RECIPE_REVIEW_REQUIRED")
            ready = not reasons
            items.append({"product_id": product_id, "ready": ready, "reasons": reasons})
            if ready:
                activate.append(product_id)
                for value in variants:
                    variant = await self.menu_repository.get_variant(
                        context.organization_id, source_to_target[value.source_key]
                    )
                    if variant is None:
                        raise ImportValidationFailed("Imported variant disappeared")
                    await self.menu_repository.update_variant(
                        ProductVariant(
                            variant.id,
                            variant.organization_id,
                            variant.product_id,
                            variant.name,
                            variant.sku,
                            variant.base_price_minor,
                            variant.is_default,
                            ProductStatus.ACTIVE,
                            variant.sort_order,
                            variant.created_at,
                            datetime.now(UTC),
                        )
                    )
        if activate:
            for product_id in activate:
                product = await self.menu_repository.get_product(
                    context.organization_id, product_id
                )
                if product is None:
                    raise ImportValidationFailed("Imported product disappeared")
                category = await self.menu_repository.get_category(
                    context.organization_id, product.category_id
                )
                if category is None or not category.is_active:
                    raise ImportValidationFailed("Product category is unavailable")
                await self.menu_repository.update_product(
                    Product(
                        product.id,
                        product.organization_id,
                        product.category_id,
                        product.name,
                        product.description,
                        product.image_url,
                        ProductStatus.ACTIVE,
                        product.created_at,
                        datetime.now(UTC),
                    )
                )
            if self.audit:
                await self.audit.record(
                    action="ONBOARDING_PRODUCTS_ACTIVATED",
                    resource_type="onboarding_import_run",
                    organization_id=context.organization_id,
                    actor_user_id=context.user_id,
                    resource_id=run.id,
                    metadata={"activated_count": len(activate)},
                )
        await self.session.flush()
        return items, len(activate)

    async def _category(
        self, context: TenantContext, entity: ImportEntity, now: datetime
    ) -> tuple[UUID, bool]:
        name = _name(entity.payload, "name", 150)
        existing = next(
            (
                value
                for value in await self.menu_repository.list_categories(
                    context.organization_id
                )
                if value.name.casefold() == name.casefold()
            ),
            None,
        )
        if existing:
            return existing.id, False
        target = uuid4()
        await self.menu_repository.add_category(
            Category(
                target,
                context.organization_id,
                name,
                int(entity.payload.get("sort_order", 0)),
                True,
                now,
                now,
            )
        )
        return target, True

    async def _inventory_item(
        self, context: TenantContext, entity: ImportEntity, now: datetime
    ) -> UUID:
        name = _name(entity.payload, "name", 150)
        sku = _optional_text(entity.payload.get("sku"), 100)
        unit = str(entity.payload.get("base_unit"))
        existing = None
        if sku:
            existing = await self.session.scalar(
                select(InventoryItemModel).where(
                    InventoryItemModel.organization_id == context.organization_id,
                    InventoryItemModel.sku == sku,
                )
            )
            if existing is not None and existing.base_unit != unit:
                raise ImportValidationFailed("INVENTORY_SKU_UNIT_CONFLICT")
        if existing is None:
            same_name = list(
                await self.session.scalars(
                    select(InventoryItemModel).where(
                        InventoryItemModel.organization_id == context.organization_id,
                        func.lower(InventoryItemModel.name) == name.casefold(),
                    )
                )
            )
            existing = next((value for value in same_name if value.base_unit == unit), None)
            if same_name and existing is None:
                raise ImportValidationFailed("INVENTORY_NAME_UNIT_CONFLICT")
        if existing:
            return existing.id
        target = uuid4()
        await self.inventory_repository.add_item(
            InventoryItem(
                target,
                context.organization_id,
                name,
                sku,
                UnitCode(unit),
                True,
                now,
                now,
            )
        )
        return target

    async def _recipe(
        self,
        context: TenantContext,
        entity: ImportEntity,
        targets: dict[str, UUID],
        now: datetime,
    ) -> UUID:
        variant_id = _reference(targets, entity, "variant_key")
        recipe_id = uuid4()
        components: list[RecipeComponent] = []
        for order, component in enumerate(entity.payload.get("components", [])):
            if not isinstance(component, dict):
                raise ImportValidationFailed("Invalid recipe component")
            item_id = targets.get(str(component.get("inventory_item_key")))
            if item_id is None:
                raise ImportValidationFailed("Recipe inventory reference not found")
            quantity = await self._base_quantity(
                item_id,
                Decimal(str(component.get("quantity"))),
                str(component.get("unit")),
            )
            components.append(
                RecipeComponent(uuid4(), recipe_id, item_id, quantity, order, now, now)
            )
        await self.menu_repository.replace_recipe(
            Recipe(
                recipe_id,
                context.organization_id,
                variant_id,
                str(entity.payload.get("name") or "Imported recipe")[:200],
                Decimal("1"),
                True,
                now,
                now,
                tuple(components),
            )
        )
        return recipe_id

    async def _modifier_components(
        self,
        entity: ImportEntity,
        targets: dict[str, UUID],
        option_id: UUID,
        now: datetime,
    ) -> tuple[ModifierOptionComponent, ...]:
        result: list[ModifierOptionComponent] = []
        for order, delta in enumerate(entity.payload.get("inventory_deltas", [])):
            if not isinstance(delta, dict):
                raise ImportValidationFailed("Invalid modifier inventory delta")
            item_id = targets.get(str(delta.get("inventory_item_key")))
            if item_id is None:
                raise ImportValidationFailed("Modifier inventory reference not found")
            quantity = await self._base_quantity(
                item_id, Decimal(str(delta.get("quantity"))), str(delta.get("unit"))
            )
            result.append(
                ModifierOptionComponent(uuid4(), option_id, item_id, quantity, order, now, now)
            )
        return tuple(result)

    async def _base_quantity(self, item_id: UUID, quantity: Decimal, unit: str) -> Decimal:
        base_unit = await self.session.scalar(
            select(InventoryItemModel.base_unit).where(InventoryItemModel.id == item_id)
        )
        if base_unit is None:
            raise ImportValidationFailed("Inventory item not found")
        try:
            return to_base_quantity(quantity, UnitCode(unit), UnitCode(base_unit))
        except (ValueError, TypeError) as exc:
            raise ImportValidationFailed("Invalid component unit or quantity") from exc

    async def _opening_balance(
        self,
        context: TenantContext,
        run: ImportRun,
        entities: list[ImportEntity],
        targets: dict[str, UUID],
    ) -> None:
        warehouse_id = await self.session.scalar(
            select(WarehouseModel.id)
            .where(
                WarehouseModel.organization_id == context.organization_id,
                WarehouseModel.location_id == run.location_id,
                WarehouseModel.is_active.is_(True),
            )
            .order_by(WarehouseModel.created_at, WarehouseModel.id)
        )
        if warehouse_id is None:
            raise ImportValidationFailed("OPENING_BALANCE_WAREHOUSE_REQUIRED")
        lines: list[QuantityInput] = []
        for entity in entities:
            item_id = _reference(targets, entity, "inventory_item_key")
            quantity = Decimal(str(entity.payload.get("quantity")))
            unit = UnitCode(str(entity.payload.get("unit")))
            cost_minor = entity.payload.get("unit_cost_minor")
            cost_factor = Decimal(str(entity.payload.get("unit_cost_base_factor", "1")))
            unit_cost = (
                Decimal(str(cost_minor)) / 100 / cost_factor if cost_minor is not None else None
            )
            lines.append(QuantityInput(item_id, quantity, unit, unit_cost_amount=unit_cost))
        staged = await self.inventory.create_and_post_staged(
            context,
            CreateAndPostCommand(
                organization_id=context.organization_id,
                user_id=context.user_id,
                warehouse_id=warehouse_id,
                type=InventoryTransactionType.OPENING_BALANCE,
                note="Imported opening balance",
                lines=tuple(lines),
                idempotency_key=f"onboarding:{run.id}:opening-balance",
            ),
        )
        await self.sink.stage_many(staged.events)
        for entity in entities:
            entity.target_id = staged.detail.transaction.id
        if self.audit:
            await self.audit.record(
                action="OPENING_BALANCE_IMPORTED",
                resource_type="inventory_transaction",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=staged.detail.transaction.id,
                metadata={"import_run_id": str(run.id), "line_count": len(lines)},
            )

    async def _assert_location(self, organization_id: UUID, location_id: UUID) -> None:
        if not await self.session.scalar(
            select(LocationModel.id).where(
                LocationModel.organization_id == organization_id,
                LocationModel.id == location_id,
                LocationModel.is_active.is_(True),
            )
        ):
            raise ImportValidationFailed("Location is outside the tenant")

    async def _target_owned(self, context: TenantContext, entity: ImportEntity) -> bool:
        model = {
            ImportEntityType.CATEGORY: MenuCategoryModel,
            ImportEntityType.INVENTORY_ITEM: InventoryItemModel,
            ImportEntityType.PRODUCT: ProductModel,
            ImportEntityType.VARIANT: ProductVariantModel,
        }.get(entity.entity_type)
        if model is not None:
            return bool(
                await self.session.scalar(
                    select(model.id).where(
                        model.organization_id == context.organization_id,
                        model.id == entity.target_id,
                    )
                )
            )
        secondary_model = {
            ImportEntityType.RECIPE: RecipeModel,
            ImportEntityType.MODIFIER_GROUP: ModifierGroupModel,
            ImportEntityType.MODIFIER_OPTION: ModifierOptionModel,
            ImportEntityType.LOCATION_PRICE: VariantPriceModel,
        }.get(entity.entity_type)
        if secondary_model is not None:
            return bool(
                await self.session.scalar(
                    select(secondary_model.id).where(
                        secondary_model.organization_id == context.organization_id,
                        secondary_model.id == entity.target_id,
                    )
                )
            )
        return False


def _reference(targets: dict[str, UUID], entity: ImportEntity, field: str) -> UUID:
    value = targets.get(_reference_from_payload(entity.payload, field))
    if value is None:
        raise ImportValidationFailed(f"Missing canonical reference: {field}")
    return value


def _reference_from_payload(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ImportValidationFailed(f"Missing canonical reference: {field}")
    return value


def _name(payload: dict[str, object], field: str, limit: int) -> str:
    value = str(payload.get(field, "")).strip()
    if not value or len(value) > limit:
        raise ImportValidationFailed(f"Invalid {field}")
    return value


def _optional_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if len(normalized) > limit:
        raise ImportValidationFailed("Text field is too long")
    return normalized or None


def _minor(payload: dict[str, object], field: str) -> int:
    try:
        value = int(str(payload[field]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ImportValidationFailed(f"Invalid {field}") from exc
    if value < 0 or value > min(MAX_BIGINT, MAX_NUMERIC_20_6_MINOR):
        raise ImportValidationFailed(f"Invalid {field}")
    return value


def entity_has_valid_recipe(run: ImportRun, variant_key: str) -> bool:
    return any(
        value.entity_type is ImportEntityType.RECIPE
        and value.resolution is not ImportResolution.SKIP
        and value.payload.get("variant_key") == variant_key
        and isinstance(value.payload.get("components"), list)
        and bool(value.payload["components"])
        for value in run.entities
    )
