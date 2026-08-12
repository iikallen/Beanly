from decimal import Decimal

import pytest

from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.onboarding.application.template_service import TemplateService
from beanly.modules.onboarding.domain.enums import ImportEntityType


@pytest.mark.parametrize(
    "code",
    (
        "classic_coffee_shop",
        "specialty_coffee",
        "coffee_bakery",
        "takeaway_coffee",
    ),
)
def test_versioned_template_is_a_valid_canonical_draft(code: str) -> None:
    draft = TemplateService().draft(code, 1)
    # Provenance must use the immutable machine code, never a translated/display label.
    assert draft.source_name == code
    assert draft.source_version == 1
    by_key = {entity.source_key: entity for entity in draft.entities}
    assert len(by_key) == len(draft.entities)
    assert tuple(entity.sort_order for entity in draft.entities) == tuple(
        range(len(draft.entities))
    )

    for entity in draft.entities:
        assert entity.source_key.strip() == entity.source_key
        assert entity.source_key
        assert not entity.error_codes
        if entity.entity_type is ImportEntityType.PRODUCT:
            assert entity.payload["category_key"] in by_key
            assert by_key[entity.payload["category_key"]].entity_type is ImportEntityType.CATEGORY
            assert entity.payload["status"] == "DRAFT"
        elif entity.entity_type is ImportEntityType.VARIANT:
            assert entity.payload["product_key"] in by_key
            assert by_key[entity.payload["product_key"]].entity_type is ImportEntityType.PRODUCT
            assert entity.payload["status"] == "DRAFT"
            price = Decimal(str(entity.payload["price_minor"]))
            assert price == price.to_integral_value()
            assert 0 <= price <= MAX_NUMERIC_20_6_MINOR
        elif entity.entity_type is ImportEntityType.RECIPE:
            assert entity.payload["variant_key"] in by_key
            assert entity.payload["review_required"] is True
            for component in entity.payload["components"]:
                assert component["inventory_item_key"] in by_key
        elif entity.entity_type is ImportEntityType.MODIFIER_GROUP:
            assert entity.payload["variant_key"] in by_key
        elif entity.entity_type is ImportEntityType.MODIFIER_OPTION:
            assert entity.payload["group_key"] in by_key


def test_classic_template_contains_the_promised_starter_menu_facts() -> None:
    draft = TemplateService().draft("classic_coffee_shop", 1)
    counts = {
        entity_type: sum(
            entity.entity_type is entity_type for entity in draft.entities
        )
        for entity_type in ImportEntityType
    }
    assert counts[ImportEntityType.CATEGORY] == 4
    assert counts[ImportEntityType.PRODUCT] >= 10
    assert counts[ImportEntityType.VARIANT] >= counts[ImportEntityType.PRODUCT]
    assert counts[ImportEntityType.INVENTORY_ITEM] >= 4
    assert counts[ImportEntityType.RECIPE] >= 1
    assert counts[ImportEntityType.MODIFIER_GROUP] >= 1
    assert counts[ImportEntityType.MODIFIER_OPTION] >= 1


def test_template_metadata_is_immutable_and_matches_payload() -> None:
    items = TemplateService().list()
    assert {item["code"] for item in items} == {
        "classic_coffee_shop",
        "specialty_coffee",
        "coffee_bakery",
        "takeaway_coffee",
    }
    assert all(item["version"] == 1 for item in items)
    for item in items:
        draft = TemplateService().draft(str(item["code"]), int(item["version"]))
        assert item["product_count"] == sum(
            entity.entity_type is ImportEntityType.PRODUCT for entity in draft.entities
        )
        assert item["category_count"] == sum(
            entity.entity_type is ImportEntityType.CATEGORY for entity in draft.entities
        )
        assert item["has_draft_recipes"] is any(
            entity.entity_type is ImportEntityType.RECIPE for entity in draft.entities
        )


def _inventory_references(draft) -> set[str]:
    references: set[str] = set()
    for entity in draft.entities:
        if entity.entity_type is ImportEntityType.RECIPE:
            references.update(
                str(component["inventory_item_key"])
                for component in entity.payload["components"]
            )
        elif entity.entity_type is ImportEntityType.MODIFIER_OPTION:
            references.update(
                str(delta["inventory_item_key"])
                for delta in entity.payload.get("inventory_deltas", [])
            )
    return references


def test_classic_packaging_option_is_exact_and_size_aware() -> None:
    service = TemplateService()
    without_packaging = service.draft(
        "classic_coffee_shop",
        1,
        {"sizes": ["250", "350"], "packaging": False},
    )
    without_inventory = {
        entity.source_key
        for entity in without_packaging.entities
        if entity.entity_type is ImportEntityType.INVENTORY_ITEM
    }
    assert not any("cup" in key or "lid" in key for key in without_inventory)
    assert not any(
        "cup" in key or "lid" in key for key in _inventory_references(without_packaging)
    )

    with_packaging = service.draft(
        "classic_coffee_shop",
        1,
        {"sizes": ["250", "350"], "packaging": True},
    )
    with_inventory = {
        entity.source_key
        for entity in with_packaging.entities
        if entity.entity_type is ImportEntityType.INVENTORY_ITEM
    }
    assert {
        "inventory:cup-250",
        "inventory:lid-250",
        "inventory:cup-350",
        "inventory:lid-350",
    } <= with_inventory
    assert _inventory_references(with_packaging) <= with_inventory


def test_classic_selected_modifiers_reference_canonical_inventory() -> None:
    draft = TemplateService().draft(
        "classic_coffee_shop",
        1,
        {
            "sizes": ["350"],
            "alternative_milks": ["Oat milk", "Lactose-free milk"],
            "extras": ["Extra shot", "Syrup vanilla"],
            "packaging": False,
        },
    )
    inventory = {
        entity.source_key
        for entity in draft.entities
        if entity.entity_type is ImportEntityType.INVENTORY_ITEM
    }
    options = {
        str(entity.payload["name"]): entity
        for entity in draft.entities
        if entity.entity_type is ImportEntityType.MODIFIER_OPTION
    }
    for name in ("Oat milk", "Lactose-free milk", "Extra shot", "Syrup vanilla"):
        assert name in options
        assert options[name].payload["inventory_deltas"]
    assert _inventory_references(draft) <= inventory


def test_classic_has_one_default_variant_and_recipe_references_selected_variant() -> None:
    draft = TemplateService().draft(
        "classic_coffee_shop",
        1,
        {"sizes": ["250", "350"], "packaging": False},
    )
    variants = {
        entity.source_key: entity
        for entity in draft.entities
        if entity.entity_type is ImportEntityType.VARIANT
    }
    defaults: dict[str, int] = {}
    for variant in variants.values():
        product_key = str(variant.payload["product_key"])
        defaults[product_key] = defaults.get(product_key, 0) + int(
            bool(variant.payload["is_default"])
        )
    assert defaults and set(defaults.values()) == {1}
    for recipe in (
        entity
        for entity in draft.entities
        if entity.entity_type is ImportEntityType.RECIPE
    ):
        assert recipe.payload["variant_key"] in variants
        assert variants[recipe.payload["variant_key"]].payload["name"] in {"250", "Default"}
