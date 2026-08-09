from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator

from beanly.modules.inventory.domain.value_objects import UnitCode, decimal_string
from beanly.modules.menu.domain.entities import (
    Category,
    Product,
    ProductLocationSetting,
    ProductVariant,
    RecipeCost,
    RecipeDetail,
    VariantPrice,
)
from beanly.modules.menu.domain.enums import ProductStatus, RecipeCostStatus


class CategoryRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=150)]
    sort_order: int = 0


class CategoryPatchRequest(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=150)] = None
    sort_order: int | None = None


class CategoryResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, value: Category) -> "CategoryResponse":
        return cls(**{field: getattr(value, field) for field in cls.model_fields})


class VariantCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)] = "Default"
    sku: Annotated[str | None, Field(max_length=100)] = None
    base_price_minor: Annotated[int, Field(ge=0, le=9223372036854775807)] = 0
    is_default: bool = False
    sort_order: int = 0


class VariantPatchRequest(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    sku: Annotated[str | None, Field(max_length=100)] = None
    base_price_minor: Annotated[int | None, Field(ge=0, le=9223372036854775807)] = None
    is_default: bool | None = None
    sort_order: int | None = None
    status: ProductStatus | None = None


class ProductCreateRequest(BaseModel):
    category_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str | None, Field(max_length=4000)] = None
    image_url: Annotated[str | None, Field(max_length=2000)] = None
    default_variant: VariantCreateRequest | None = None


class ProductPatchRequest(BaseModel):
    category_id: UUID | None = None
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=4000)] = None
    image_url: Annotated[str | None, Field(max_length=2000)] = None
    status: ProductStatus | None = None


class VariantResponse(BaseModel):
    id: UUID
    organization_id: UUID
    product_id: UUID
    name: str
    sku: str | None
    base_price_minor: str
    location_price_minor: str | None
    effective_price_minor: str
    is_default: bool
    status: ProductStatus
    sort_order: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, value: ProductVariant) -> "VariantResponse":
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            product_id=value.product_id,
            name=value.name,
            sku=value.sku,
            base_price_minor=str(value.base_price_minor),
            location_price_minor=(
                str(value.location_price_minor) if value.location_price_minor is not None else None
            ),
            effective_price_minor=str(
                value.effective_price_minor
                if value.effective_price_minor is not None
                else value.base_price_minor
            ),
            is_default=value.is_default,
            status=value.status,
            sort_order=value.sort_order,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class ProductResponse(BaseModel):
    id: UUID
    organization_id: UUID
    category_id: UUID
    name: str
    description: str | None
    image_url: str | None
    status: ProductStatus
    created_at: datetime
    updated_at: datetime
    variants: list[VariantResponse]
    is_available: bool | None
    is_visible: bool | None

    @classmethod
    def from_entity(cls, value: Product) -> "ProductResponse":
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            category_id=value.category_id,
            name=value.name,
            description=value.description,
            image_url=value.image_url,
            status=value.status,
            created_at=value.created_at,
            updated_at=value.updated_at,
            variants=[VariantResponse.from_entity(variant) for variant in value.variants],
            is_available=value.is_available,
            is_visible=value.is_visible,
        )


class RecipeComponentRequest(BaseModel):
    inventory_item_id: UUID
    quantity: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
    unit: UnitCode
    sort_order: int = 0

    @field_validator("quantity", mode="before")
    @classmethod
    def decimal_string_only(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("quantity must be a decimal string")
        return value


class RecipeRequest(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    yield_quantity: Decimal = Decimal(1)
    components: Annotated[list[RecipeComponentRequest], Field(min_length=1, max_length=500)]

    @field_validator("yield_quantity", mode="before")
    @classmethod
    def yield_decimal_string_only(cls, value: object) -> object:
        if isinstance(value, int) and value == 1:
            return "1"
        if not isinstance(value, str):
            raise ValueError("yield_quantity must be a decimal string")
        return value


class RecipeComponentResponse(BaseModel):
    id: UUID
    inventory_item_id: UUID
    item_name: str
    base_unit: UnitCode
    quantity: Decimal
    sort_order: int

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return decimal_string(value)


class RecipeResponse(BaseModel):
    id: UUID
    variant_id: UUID
    name: str
    yield_quantity: Decimal
    is_active: bool
    components: list[RecipeComponentResponse]

    @field_serializer("yield_quantity")
    def serialize_yield(self, value: Decimal) -> str:
        return decimal_string(value)

    @classmethod
    def from_detail(cls, value: RecipeDetail) -> "RecipeResponse":
        return cls(
            id=value.recipe.id,
            variant_id=value.recipe.product_variant_id,
            name=value.recipe.name,
            yield_quantity=value.recipe.yield_quantity,
            is_active=value.recipe.is_active,
            components=[
                RecipeComponentResponse(
                    id=detail.component.id,
                    inventory_item_id=detail.component.inventory_item_id,
                    item_name=detail.item_name,
                    base_unit=detail.base_unit,
                    quantity=detail.component.quantity,
                    sort_order=detail.component.sort_order,
                )
                for detail in value.components
            ],
        )


class CostComponentResponse(BaseModel):
    inventory_item_id: UUID
    name: str
    quantity: Decimal
    base_unit: UnitCode
    unit_cost: Decimal | None
    cost: Decimal | None

    @field_serializer("quantity", "unit_cost", "cost")
    def serialize_decimals(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None


class RecipeCostResponse(BaseModel):
    variant_id: UUID
    price_minor: str
    recipe_cost: Decimal | None
    food_cost_percent: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    status: RecipeCostStatus
    missing_cost_items: list[str]
    components: list[CostComponentResponse]

    @field_serializer("recipe_cost", "food_cost_percent", "gross_profit", "gross_margin_percent")
    def serialize_decimals(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None

    @classmethod
    def from_entity(cls, value: RecipeCost) -> "RecipeCostResponse":
        return cls(
            variant_id=value.variant_id,
            price_minor=str(value.price_minor),
            recipe_cost=value.recipe_cost,
            food_cost_percent=value.food_cost_percent,
            gross_profit=value.gross_profit,
            gross_margin_percent=value.gross_margin_percent,
            status=value.status,
            missing_cost_items=list(value.missing_cost_items),
            components=[
                CostComponentResponse(
                    inventory_item_id=component.inventory_item_id,
                    name=component.name,
                    quantity=component.quantity,
                    base_unit=component.base_unit,
                    unit_cost=component.unit_cost,
                    cost=component.cost,
                )
                for component in value.components
            ],
        )


class VariantPriceRequest(BaseModel):
    price_minor: Annotated[int | None, Field(ge=0, le=9223372036854775807)]


class VariantPriceResponse(BaseModel):
    variant_id: UUID
    location_id: UUID
    price_minor: str | None

    @classmethod
    def from_entity(
        cls, variant_id: UUID, location_id: UUID, value: VariantPrice | None
    ) -> "VariantPriceResponse":
        return cls(
            variant_id=variant_id,
            location_id=location_id,
            price_minor=str(value.price_minor) if value is not None else None,
        )


class ProductLocationRequest(BaseModel):
    is_available: bool
    is_visible: bool


class ProductLocationResponse(BaseModel):
    product_id: UUID
    location_id: UUID
    is_available: bool
    is_visible: bool

    @classmethod
    def from_entity(cls, value: ProductLocationSetting) -> "ProductLocationResponse":
        return cls(
            product_id=value.product_id,
            location_id=value.location_id,
            is_available=value.is_available,
            is_visible=value.is_visible,
        )


class MenuCategoryResponse(BaseModel):
    id: UUID
    name: str
    sort_order: int
    products: list[ProductResponse]


class MenuResponse(BaseModel):
    location_id: UUID
    categories: list[MenuCategoryResponse]


class BatchCostVariantResponse(BaseModel):
    variant_id: UUID
    price_minor: str
    recipe_cost: Decimal | None
    status: RecipeCostStatus
    missing_cost_items: list[str]

    @field_serializer("recipe_cost")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None

    @classmethod
    def from_entity(cls, value: RecipeCost) -> "BatchCostVariantResponse":
        return cls(
            variant_id=value.variant_id,
            price_minor=str(value.price_minor),
            recipe_cost=value.recipe_cost,
            status=value.status,
            missing_cost_items=list(value.missing_cost_items),
        )


class BatchCostsResponse(BaseModel):
    warehouse_id: UUID
    variants: list[BatchCostVariantResponse]
