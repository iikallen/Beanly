from dataclasses import dataclass
from uuid import UUID

from beanly.modules.onboarding.domain.enums import ImportEntityType, ImportResolution


@dataclass(frozen=True, slots=True)
class CanonicalImportEntity:
    """Provider-neutral draft entity. References use stable source keys, never row numbers."""

    entity_type: ImportEntityType
    source_key: str
    payload: dict[str, object]
    resolution: ImportResolution = ImportResolution.CREATE
    target_id: UUID | None = None
    error_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class CanonicalImportDraft:
    source_name: str
    source_version: int | None
    entities: tuple[CanonicalImportEntity, ...]


# Canonical payload contracts. Monetary amounts are decimal strings in minor units.
# CATEGORY: {name, sort_order?}
# INVENTORY_ITEM: {name, sku?, base_unit: g|ml|pcs}
# PRODUCT: {category_key, name, description?, status: DRAFT}
# VARIANT: {product_key, name, sku?, price_minor, is_default?, sort_order?}
# RECIPE: {variant_key, components:[{inventory_item_key, quantity, unit}], review_required}
# MODIFIER_GROUP: {variant_key, name, selection_type, min_selections, max_selections}
# MODIFIER_OPTION: {group_key, name, price_delta_minor, inventory_deltas?}
# LOCATION_PRICE: {variant_key, location_id, price_minor}
# OPENING_BALANCE: {inventory_item_key, warehouse_id, quantity, unit, unit_cost_minor?}
