from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CategoryCreated:
    category_id: UUID


@dataclass(frozen=True, slots=True)
class ProductCreated:
    product_id: UUID


@dataclass(frozen=True, slots=True)
class ProductUpdated:
    product_id: UUID


@dataclass(frozen=True, slots=True)
class ProductArchived:
    product_id: UUID


@dataclass(frozen=True, slots=True)
class VariantCreated:
    variant_id: UUID


@dataclass(frozen=True, slots=True)
class VariantPriceChanged:
    variant_id: UUID
    location_id: UUID | None


@dataclass(frozen=True, slots=True)
class RecipeCreated:
    recipe_id: UUID


@dataclass(frozen=True, slots=True)
class RecipeUpdated:
    recipe_id: UUID


@dataclass(frozen=True, slots=True)
class RecipeCostChanged:
    recipe_id: UUID
