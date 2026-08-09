from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode


@dataclass(frozen=True, slots=True)
class VariantInput:
    name: str = "Default"
    sku: str | None = None
    base_price_minor: int = 0


@dataclass(frozen=True, slots=True)
class RecipeComponentInput:
    inventory_item_id: UUID
    quantity: Decimal
    unit: UnitCode
    sort_order: int
