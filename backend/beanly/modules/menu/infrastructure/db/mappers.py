from beanly.modules.menu.domain.entities import (
    Category,
    ModifierGroup,
    ModifierOption,
    ModifierOptionComponent,
    ModifierOptionLocationSetting,
    ModifierOptionPrice,
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


def to_category(model: MenuCategoryModel) -> Category:
    return Category(
        model.id,
        model.organization_id,
        model.name,
        model.sort_order,
        model.is_active,
        model.created_at,
        model.updated_at,
    )


def to_variant(model: ProductVariantModel, location_id=None) -> ProductVariant:
    return ProductVariant(
        model.id,
        model.organization_id,
        model.product_id,
        model.name,
        model.sku,
        model.base_price_minor,
        model.is_default,
        ProductStatus(model.status),
        model.sort_order,
        model.created_at,
        model.updated_at,
        modifier_groups=tuple(
            to_modifier_group(value, location_id, active_only=True)
            for value in sorted(
                model.__dict__.get("modifier_groups", ()),
                key=lambda x: (x.sort_order, x.id),
            )
            if value.is_active
        ),
    )


def to_product(model: ProductModel, location_id=None) -> Product:
    return Product(
        model.id,
        model.organization_id,
        model.category_id,
        model.name,
        model.description,
        model.image_url,
        ProductStatus(model.status),
        model.created_at,
        model.updated_at,
        tuple(
            to_variant(value, location_id)
            for value in sorted(model.variants, key=lambda x: (x.sort_order, x.id))
        ),
    )


def to_component(model: RecipeComponentModel) -> RecipeComponent:
    return RecipeComponent(
        model.id,
        model.recipe_id,
        model.inventory_item_id,
        model.quantity,
        model.sort_order,
        model.created_at,
        model.updated_at,
    )


def to_recipe(model: RecipeModel) -> Recipe:
    return Recipe(
        model.id,
        model.organization_id,
        model.product_variant_id,
        model.name,
        model.yield_quantity,
        model.is_active,
        model.created_at,
        model.updated_at,
        tuple(
            to_component(value)
            for value in sorted(model.components, key=lambda x: (x.sort_order, x.id))
        ),
    )


def to_variant_price(model: VariantPriceModel) -> VariantPrice:
    return VariantPrice(
        model.id,
        model.organization_id,
        model.location_id,
        model.product_variant_id,
        model.price_minor,
        model.created_at,
        model.updated_at,
    )


def to_product_location(model: ProductLocationSettingModel) -> ProductLocationSetting:
    return ProductLocationSetting(
        model.id,
        model.organization_id,
        model.location_id,
        model.product_id,
        model.is_available,
        model.is_visible,
        model.created_at,
        model.updated_at,
    )


def to_modifier_component(model: ModifierOptionComponentModel) -> ModifierOptionComponent:
    return ModifierOptionComponent(
        model.id,
        model.modifier_option_id,
        model.inventory_item_id,
        model.quantity_delta,
        model.sort_order,
        model.created_at,
        model.updated_at,
    )


def to_modifier_option_price(model: ModifierOptionPriceModel) -> ModifierOptionPrice:
    return ModifierOptionPrice(
        model.id,
        model.organization_id,
        model.location_id,
        model.modifier_option_id,
        model.price_delta_minor,
        model.created_at,
        model.updated_at,
    )


def to_modifier_location_setting(
    model: ModifierOptionLocationSettingModel,
) -> ModifierOptionLocationSetting:
    return ModifierOptionLocationSetting(
        model.id,
        model.organization_id,
        model.location_id,
        model.modifier_option_id,
        model.is_available,
        model.created_at,
        model.updated_at,
    )


def to_modifier_option(model: ModifierOptionModel, location_id=None) -> ModifierOption:
    prices = model.__dict__.get("prices", ())
    settings = model.__dict__.get("location_settings", ())
    location_price = next(
        (value.price_delta_minor for value in prices if value.location_id == location_id), None
    )
    setting = next((value for value in settings if value.location_id == location_id), None)
    return ModifierOption(
        model.id,
        model.organization_id,
        model.modifier_group_id,
        model.name,
        model.base_price_delta_minor,
        model.is_default,
        model.sort_order,
        model.is_active,
        model.created_at,
        model.updated_at,
        tuple(
            to_modifier_component(value)
            for value in sorted(
                model.__dict__.get("components", ()), key=lambda x: (x.sort_order, x.id)
            )
        ),
        location_price,
        location_price if location_price is not None else model.base_price_delta_minor,
        setting.is_available if setting else True,
    )


def to_modifier_group(
    model: ModifierGroupModel, location_id=None, *, active_only: bool = False
) -> ModifierGroup:
    return ModifierGroup(
        model.id,
        model.organization_id,
        model.product_variant_id,
        model.name,
        ModifierSelectionType(model.selection_type),
        model.min_selections,
        model.max_selections,
        model.sort_order,
        model.is_active,
        model.created_at,
        model.updated_at,
        tuple(
            to_modifier_option(value, location_id)
            for value in sorted(
                model.__dict__.get("options", ()), key=lambda x: (x.sort_order, x.id)
            )
            if not active_only or value.is_active
        ),
    )
