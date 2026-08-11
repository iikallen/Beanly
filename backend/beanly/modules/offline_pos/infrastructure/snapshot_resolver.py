from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.offline_pos.domain.exceptions import CatalogSnapshotInvalid
from beanly.modules.sales.application.ports import (
    SellableComponentSnapshot,
    SellableItemSnapshot,
    SellableModifierSnapshot,
)


def resolve_snapshot_item(
    private_payload: dict[str, object],
    variant_id: UUID,
    selected_option_ids: tuple[UUID, ...],
) -> SellableItemSnapshot:
    variants = private_payload.get("variants")
    if not isinstance(variants, dict):
        raise CatalogSnapshotInvalid("Catalog snapshot has no variants")
    variant = variants.get(str(variant_id))
    if not isinstance(variant, dict):
        raise CatalogSnapshotInvalid("Variant is absent from the catalog snapshot")
    if not variant.get("is_available", True):
        raise CatalogSnapshotInvalid("Product was unavailable in the catalog snapshot")
    selected = {str(value) for value in selected_option_ids}
    if len(selected) != len(selected_option_ids):
        raise CatalogSnapshotInvalid("Modifier selections must be unique")
    quantities: dict[str, tuple[str, str, Decimal]] = {}
    for component in _list(variant, "components"):
        _add_component(quantities, component)
    modifiers: list[SellableModifierSnapshot] = []
    modifier_price = 0
    known: set[str] = set()
    for group in _list(variant, "modifier_groups"):
        options = _list(group, "options")
        chosen = [option for option in options if str(option.get("id")) in selected]
        count = len(chosen)
        if count < int(group["min_selections"]) or count > int(group["max_selections"]):
            raise CatalogSnapshotInvalid("Modifier selection violates snapshot constraints")
        for option in options:
            known.add(str(option.get("id")))
        for option in chosen:
            if not option.get("is_available", True):
                raise CatalogSnapshotInvalid("Selected modifier was unavailable in the snapshot")
            price = int(str(option["price_delta_minor"]))
            modifier_price += price
            modifiers.append(
                SellableModifierSnapshot(
                    UUID(str(group["id"])),
                    str(group["name"]),
                    UUID(str(option["id"])),
                    str(option["name"]),
                    price,
                    len(modifiers),
                )
            )
            for component in _list(option, "components"):
                _add_component(quantities, component)
    if selected - known:
        raise CatalogSnapshotInvalid("Modifier option is absent from the catalog snapshot")
    if any(value[2] < 0 for value in quantities.values()):
        raise CatalogSnapshotInvalid("Modifier selection produces a negative recipe quantity")
    base_price = int(str(variant["base_price_minor"]))
    unit_price = base_price + modifier_price
    if unit_price > 9223372036854775807:
        raise CatalogSnapshotInvalid("Snapshot price is outside BIGINT")
    return SellableItemSnapshot(
        UUID(str(variant["product_id"])),
        str(variant["product_name"]),
        variant_id,
        str(variant["variant_name"]),
        base_price,
        modifier_price,
        unit_price,
        tuple(modifiers),
        tuple(
            SellableComponentSnapshot(UUID(item_id), name, UnitCode(unit), quantity)
            for item_id, (name, unit, quantity) in sorted(quantities.items())
            if quantity > 0
        ),
    )


def _list(value: dict[str, object], key: str) -> list[dict[str, object]]:
    result = value.get(key, [])
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise CatalogSnapshotInvalid("Catalog snapshot structure is invalid")
    return result


def _add_component(
    quantities: dict[str, tuple[str, str, Decimal]], component: dict[str, object]
) -> None:
    item_id = str(component["inventory_item_id"])
    name = str(component["inventory_item_name"])
    unit = str(component["base_unit"])
    quantity = Decimal(str(component["quantity"]))
    current = quantities.get(item_id)
    if current is not None and current[:2] != (name, unit):
        raise CatalogSnapshotInvalid("Snapshot component metadata conflicts")
    quantities[item_id] = (name, unit, quantity + (current[2] if current else 0))
