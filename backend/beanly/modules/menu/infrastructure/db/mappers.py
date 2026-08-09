from beanly.modules.menu.domain.entities import (
    Category,
    Product,
    ProductLocationSetting,
    ProductVariant,
    Recipe,
    RecipeComponent,
    VariantPrice,
)
from beanly.modules.menu.domain.enums import ProductStatus
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
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


def to_variant(model: ProductVariantModel) -> ProductVariant:
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
    )


def to_product(model: ProductModel) -> Product:
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
            to_variant(value)
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
