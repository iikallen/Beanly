import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.customers.infrastructure.db.models import PromotionAudienceModel
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalTaxProfileModel,
    FiscalVariantProfileModel,
)
from beanly.modules.inventory.infrastructure.db.models import InventoryItemModel
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ModifierGroupModel,
    ModifierOptionComponentModel,
    ModifierOptionLocationSettingModel,
    ModifierOptionModel,
    ModifierOptionPriceModel,
    ProductLocationSettingModel,
    ProductModel,
    ProductVariantModel,
    RecipeComponentModel,
    RecipeModel,
    VariantPriceModel,
)
from beanly.modules.offline_pos.infrastructure.db.models import PosCatalogSnapshotModel
from beanly.modules.promotions.infrastructure.db.models import (
    PromotionLocationModel,
    PromotionModel,
    PromotionScheduleModel,
    PromotionTargetModel,
)


class CatalogSnapshotBuilder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        organization_id: UUID,
        location_id: UUID,
        warehouse_id: UUID,
        *,
        ttl: timedelta = timedelta(hours=24),
    ) -> PosCatalogSnapshotModel:
        categories = list(
            await self.session.scalars(
                select(MenuCategoryModel).where(
                    MenuCategoryModel.organization_id == organization_id,
                    MenuCategoryModel.is_active.is_(True),
                )
            )
        )
        products = list(
            await self.session.scalars(
                select(ProductModel).where(
                    ProductModel.organization_id == organization_id,
                    ProductModel.status == "ACTIVE",
                )
            )
        )
        product_ids = [value.id for value in products]
        variants = (
            list(
                await self.session.scalars(
                    select(ProductVariantModel).where(
                        ProductVariantModel.organization_id == organization_id,
                        ProductVariantModel.product_id.in_(product_ids),
                        ProductVariantModel.status == "ACTIVE",
                    )
                )
            )
            if product_ids
            else []
        )
        variant_ids = [value.id for value in variants]
        fiscal_profiles = (
            {
                value.product_variant_id: value
                for value in await self.session.scalars(
                    select(FiscalVariantProfileModel).where(
                        FiscalVariantProfileModel.organization_id == organization_id,
                        FiscalVariantProfileModel.product_variant_id.in_(variant_ids),
                    )
                )
            }
            if variant_ids
            else {}
        )
        tax_profiles = list(
            await self.session.scalars(
                select(FiscalTaxProfileModel)
                .where(FiscalTaxProfileModel.organization_id == organization_id)
                .order_by(FiscalTaxProfileModel.effective_from)
            )
        )
        promotion_rows = list(
            (
                await self.session.execute(
                    select(PromotionModel)
                    .outerjoin(
                        PromotionAudienceModel,
                        PromotionAudienceModel.promotion_id == PromotionModel.id,
                    )
                    .where(
                        PromotionModel.organization_id == organization_id,
                        PromotionModel.status == "ACTIVE",
                        PromotionModel.application_mode.in_(["AUTOMATIC", "MANUAL"]),
                        (
                            PromotionAudienceModel.promotion_id.is_(None)
                            | (PromotionAudienceModel.kind == "ALL")
                        ),
                    )
                    .order_by(
                        PromotionModel.priority.desc(),
                        PromotionModel.created_at,
                        PromotionModel.id,
                    )
                )
            ).scalars()
        )
        promotion_ids = [value.id for value in promotion_rows]
        promotion_locations = set(
            await self.session.scalars(
                select(PromotionLocationModel.promotion_id).where(
                    PromotionLocationModel.promotion_id.in_(promotion_ids),
                    PromotionLocationModel.location_id == location_id,
                )
            )
        )
        schedules = defaultdict(list)
        targets = defaultdict(list)
        if promotion_ids:
            for value in await self.session.scalars(
                select(PromotionScheduleModel).where(
                    PromotionScheduleModel.promotion_id.in_(promotion_ids)
                )
            ):
                schedules[value.promotion_id].append(value)
            for value in await self.session.scalars(
                select(PromotionTargetModel).where(
                    PromotionTargetModel.promotion_id.in_(promotion_ids)
                )
            ):
                targets[value.promotion_id].append(value)

        product_settings = (
            {
                value.product_id: value
                for value in await self.session.scalars(
                    select(ProductLocationSettingModel).where(
                        ProductLocationSettingModel.organization_id == organization_id,
                        ProductLocationSettingModel.location_id == location_id,
                        ProductLocationSettingModel.product_id.in_(product_ids),
                    )
                )
            }
            if product_ids
            else {}
        )
        prices = (
            {
                value.product_variant_id: value.price_minor
                for value in await self.session.scalars(
                    select(VariantPriceModel).where(
                        VariantPriceModel.organization_id == organization_id,
                        VariantPriceModel.location_id == location_id,
                        VariantPriceModel.product_variant_id.in_(variant_ids),
                    )
                )
            }
            if variant_ids
            else {}
        )
        recipes = (
            {
                value.product_variant_id: value
                for value in await self.session.scalars(
                    select(RecipeModel).where(
                        RecipeModel.organization_id == organization_id,
                        RecipeModel.product_variant_id.in_(variant_ids),
                        RecipeModel.is_active.is_(True),
                    )
                )
            }
            if variant_ids
            else {}
        )
        recipe_ids = [value.id for value in recipes.values()]
        recipe_components = (
            list(
                (
                    await self.session.execute(
                        select(RecipeComponentModel, InventoryItemModel)
                        .join(
                            InventoryItemModel,
                            InventoryItemModel.id == RecipeComponentModel.inventory_item_id,
                        )
                        .where(RecipeComponentModel.recipe_id.in_(recipe_ids))
                    )
                ).all()
            )
            if recipe_ids
            else []
        )
        components_by_recipe: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for component, item in recipe_components:
            components_by_recipe[component.recipe_id].append(
                _component(item.id, item.name, item.base_unit, component.quantity)
            )

        groups = (
            list(
                await self.session.scalars(
                    select(ModifierGroupModel).where(
                        ModifierGroupModel.organization_id == organization_id,
                        ModifierGroupModel.product_variant_id.in_(variant_ids),
                        ModifierGroupModel.is_active.is_(True),
                    )
                )
            )
            if variant_ids
            else []
        )
        group_ids = [value.id for value in groups]
        options = (
            list(
                await self.session.scalars(
                    select(ModifierOptionModel).where(
                        ModifierOptionModel.organization_id == organization_id,
                        ModifierOptionModel.modifier_group_id.in_(group_ids),
                        ModifierOptionModel.is_active.is_(True),
                    )
                )
            )
            if group_ids
            else []
        )
        option_ids = [value.id for value in options]
        option_prices = (
            {
                value.modifier_option_id: value.price_delta_minor
                for value in await self.session.scalars(
                    select(ModifierOptionPriceModel).where(
                        ModifierOptionPriceModel.organization_id == organization_id,
                        ModifierOptionPriceModel.location_id == location_id,
                        ModifierOptionPriceModel.modifier_option_id.in_(option_ids),
                    )
                )
            }
            if option_ids
            else {}
        )
        option_availability = (
            {
                value.modifier_option_id: value.is_available
                for value in await self.session.scalars(
                    select(ModifierOptionLocationSettingModel).where(
                        ModifierOptionLocationSettingModel.organization_id == organization_id,
                        ModifierOptionLocationSettingModel.location_id == location_id,
                        ModifierOptionLocationSettingModel.modifier_option_id.in_(option_ids),
                    )
                )
            }
            if option_ids
            else {}
        )
        option_components = (
            list(
                (
                    await self.session.execute(
                        select(ModifierOptionComponentModel, InventoryItemModel)
                        .join(
                            InventoryItemModel,
                            InventoryItemModel.id == ModifierOptionComponentModel.inventory_item_id,
                        )
                        .where(ModifierOptionComponentModel.modifier_option_id.in_(option_ids))
                    )
                ).all()
            )
            if option_ids
            else []
        )
        components_by_option: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for component, item in option_components:
            components_by_option[component.modifier_option_id].append(
                _component(item.id, item.name, item.base_unit, component.quantity_delta)
            )

        options_by_group: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        private_options_by_group: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for option in sorted(options, key=lambda value: (value.sort_order, str(value.id))):
            available = option_availability.get(option.id, True)
            price = option_prices.get(option.id, option.base_price_delta_minor)
            public_option = {
                "id": str(option.id),
                "name": option.name,
                "base_price_delta_minor": str(option.base_price_delta_minor),
                "location_price_delta_minor": (
                    str(option_prices[option.id]) if option.id in option_prices else None
                ),
                "effective_price_delta_minor": str(price),
                "is_default": option.is_default,
                "sort_order": option.sort_order,
                "is_available": available,
            }
            options_by_group[option.modifier_group_id].append(public_option)
            private_options_by_group[option.modifier_group_id].append(
                {
                    "id": str(option.id),
                    "name": option.name,
                    "price_delta_minor": str(price),
                    "is_default": option.is_default,
                    "sort_order": option.sort_order,
                    "is_available": available,
                    "components": components_by_option[option.id],
                }
            )

        groups_by_variant: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        private_groups_by_variant: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for group in sorted(groups, key=lambda value: (value.sort_order, str(value.id))):
            common = {
                "id": str(group.id),
                "name": group.name,
                "selection_type": group.selection_type,
                "min_selections": group.min_selections,
                "max_selections": group.max_selections,
                "sort_order": group.sort_order,
                "is_active": True,
            }
            groups_by_variant[group.product_variant_id].append(
                {**common, "options": options_by_group[group.id]}
            )
            private_groups_by_variant[group.product_variant_id].append(
                {**common, "options": private_options_by_group[group.id]}
            )

        variants_by_product: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        private_variants: dict[str, object] = {}
        products_by_id = {value.id: value for value in products}
        for variant in sorted(variants, key=lambda value: (value.sort_order, str(value.id))):
            product = products_by_id[variant.product_id]
            setting = product_settings.get(product.id)
            recipe = recipes.get(variant.id)
            if recipe is None:
                continue
            price = prices.get(variant.id, variant.base_price_minor)
            variants_by_product[variant.product_id].append(
                {
                    "id": str(variant.id),
                    "organization_id": str(organization_id),
                    "product_id": str(product.id),
                    "name": variant.name,
                    "sku": variant.sku,
                    "base_price_minor": str(variant.base_price_minor),
                    "location_price_minor": (
                        str(prices[variant.id]) if variant.id in prices else None
                    ),
                    "effective_price_minor": str(price),
                    "is_default": variant.is_default,
                    "status": variant.status,
                    "sort_order": variant.sort_order,
                    "created_at": variant.created_at.isoformat(),
                    "updated_at": variant.updated_at.isoformat(),
                    "modifier_groups": groups_by_variant[variant.id],
                }
            )
            private_variants[str(variant.id)] = {
                "product_id": str(product.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "is_available": setting.is_available if setting else True,
                "base_price_minor": str(price),
                "components": components_by_recipe[recipe.id],
                "modifier_groups": private_groups_by_variant[variant.id],
                "fiscal": (
                    {
                        "fiscal_name": fiscal_profiles[variant.id].fiscal_name,
                        "nkt_code": fiscal_profiles[variant.id].nkt_code,
                        "nkt_code_type": fiscal_profiles[variant.id].nkt_code_type,
                        "unit_code": fiscal_profiles[variant.id].fiscal_unit_code,
                        "vat_rate_override": (
                            str(fiscal_profiles[variant.id].vat_rate_override)
                            if fiscal_profiles[variant.id].vat_rate_override is not None
                            else None
                        ),
                        "requires_marking": fiscal_profiles[variant.id].requires_marking,
                    }
                    if variant.id in fiscal_profiles
                    else None
                ),
            }

        products_by_category: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        for product in sorted(products, key=lambda value: (value.name.casefold(), str(value.id))):
            setting = product_settings.get(product.id)
            if setting is not None and not setting.is_visible:
                continue
            product_variants = variants_by_product[product.id]
            if not product_variants:
                continue
            products_by_category[product.category_id].append(
                {
                    "id": str(product.id),
                    "organization_id": str(organization_id),
                    "category_id": str(product.category_id),
                    "name": product.name,
                    "description": product.description,
                    "image_url": product.image_url,
                    "status": product.status,
                    "is_available": setting.is_available if setting else True,
                    "is_visible": setting.is_visible if setting else True,
                    "variants": product_variants,
                    "created_at": product.created_at.isoformat(),
                    "updated_at": product.updated_at.isoformat(),
                }
            )

        public = {
            "location_id": str(location_id),
            "promotions": [
                {
                    "promotion_id": str(value.id),
                    "created_at": value.created_at.isoformat(),
                    "name": value.pos_name,
                    "application_mode": value.application_mode,
                    "kind": value.discount_kind,
                    "scope": value.scope,
                    "percent_rate": (
                        str(value.percent_rate) if value.percent_rate is not None else None
                    ),
                    "amount_minor": (
                        str(value.amount_minor) if value.amount_minor is not None else None
                    ),
                    "fixed_price_minor": (
                        str(value.fixed_price_minor)
                        if value.fixed_price_minor is not None
                        else None
                    ),
                    "priority": value.priority,
                    "stacking": value.stacking_policy,
                    "include_modifier_price": value.include_modifier_price,
                    "requires_override_permission": value.requires_override_permission,
                    "minimum_subtotal_minor": (
                        str(value.minimum_subtotal_minor)
                        if value.minimum_subtotal_minor is not None
                        else None
                    ),
                    "maximum_discount_minor": (
                        str(value.maximum_discount_minor)
                        if value.maximum_discount_minor is not None
                        else None
                    ),
                    "valid_from": value.valid_from.isoformat() if value.valid_from else None,
                    "valid_to": value.valid_to.isoformat() if value.valid_to else None,
                    "schedules": [
                        {
                            "weekday": item.weekday,
                            "start_local_time": item.start_local_time.isoformat(),
                            "end_local_time": item.end_local_time.isoformat(),
                        }
                        for item in schedules[value.id]
                    ],
                    "targets": [
                        {
                            "role": item.role,
                            "target_type": item.target_type,
                            "target_id": str(item.target_id) if item.target_id else None,
                            "quantity": item.quantity,
                            "sort_order": item.sort_order,
                        }
                        for item in targets[value.id]
                    ],
                }
                for value in promotion_rows
                if value.all_locations or value.id in promotion_locations
            ],
            "categories": [
                {
                    "id": str(category.id),
                    "name": category.name,
                    "sort_order": category.sort_order,
                    "products": products_by_category[category.id],
                }
                for category in sorted(
                    categories, key=lambda value: (value.sort_order, str(value.id))
                )
                if products_by_category[category.id]
            ],
        }
        private = {
            "variants": private_variants,
            "tax_profiles": [
                {
                    "id": str(profile.id),
                    "country_code": profile.country_code,
                    "tax_regime_code": profile.tax_regime_code,
                    "vat_registered": profile.vat_registered,
                    "default_vat_rate": (
                        str(profile.default_vat_rate)
                        if profile.default_vat_rate is not None
                        else None
                    ),
                    "effective_from": profile.effective_from.isoformat(),
                    "effective_to": (
                        profile.effective_to.isoformat() if profile.effective_to else None
                    ),
                }
                for profile in tax_profiles
            ],
        }
        digest = hashlib.sha256(_canonical({"public": public, "private": private})).hexdigest()
        now = datetime.now(UTC)
        return PosCatalogSnapshotModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            warehouse_id=warehouse_id,
            created_at=now,
            expires_at=now + ttl,
            public_payload=public,
            private_payload=private,
            payload_hash=digest,
        )


def _component(item_id: UUID, name: str, base_unit: str, quantity: Decimal) -> dict[str, object]:
    return {
        "inventory_item_id": str(item_id),
        "inventory_item_name": name,
        "base_unit": base_unit,
        "quantity": format(quantity, "f"),
    }


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
