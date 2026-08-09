from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.menu.domain.enums import ProductStatus, RecipeCostStatus


@dataclass(frozen=True, slots=True)
class Category:
    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProductVariant:
    id: UUID
    organization_id: UUID
    product_id: UUID
    name: str
    sku: str | None
    base_price_minor: int
    is_default: bool
    status: ProductStatus
    sort_order: int
    created_at: datetime
    updated_at: datetime
    location_price_minor: int | None = None
    effective_price_minor: int | None = None


@dataclass(frozen=True, slots=True)
class Product:
    id: UUID
    organization_id: UUID
    category_id: UUID
    name: str
    description: str | None
    image_url: str | None
    status: ProductStatus
    created_at: datetime
    updated_at: datetime
    variants: tuple[ProductVariant, ...] = ()
    is_available: bool | None = None
    is_visible: bool | None = None


@dataclass(frozen=True, slots=True)
class RecipeComponent:
    id: UUID
    recipe_id: UUID
    inventory_item_id: UUID
    quantity: Decimal
    sort_order: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Recipe:
    id: UUID
    organization_id: UUID
    product_variant_id: UUID
    name: str
    yield_quantity: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime
    components: tuple[RecipeComponent, ...] = ()


@dataclass(frozen=True, slots=True)
class RecipeComponentDetail:
    component: RecipeComponent
    item_name: str
    base_unit: UnitCode


@dataclass(frozen=True, slots=True)
class RecipeDetail:
    recipe: Recipe
    components: tuple[RecipeComponentDetail, ...]


@dataclass(frozen=True, slots=True)
class VariantPrice:
    id: UUID
    organization_id: UUID
    location_id: UUID
    product_variant_id: UUID
    price_minor: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProductLocationSetting:
    id: UUID
    organization_id: UUID
    location_id: UUID
    product_id: UUID
    is_available: bool
    is_visible: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ComponentCost:
    inventory_item_id: UUID
    name: str
    quantity: Decimal
    base_unit: UnitCode
    unit_cost: Decimal | None
    cost: Decimal | None


@dataclass(frozen=True, slots=True)
class RecipeCost:
    variant_id: UUID
    price_minor: int
    recipe_cost: Decimal | None
    food_cost_percent: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    status: RecipeCostStatus
    missing_cost_items: tuple[str, ...]
    components: tuple[ComponentCost, ...]


@dataclass(frozen=True, slots=True)
class MenuProduct:
    product: Product
    effective_prices: dict[UUID, int]
