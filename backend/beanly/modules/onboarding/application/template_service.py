import json
import re
from importlib.resources import files
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from beanly.modules.onboarding.application.dto import (
    CanonicalImportDraft,
    CanonicalImportEntity,
)
from beanly.modules.onboarding.domain.enums import ImportEntityType
from beanly.modules.onboarding.domain.exceptions import TemplateNotFound

_TEMPLATE_CODES = (
    "classic_coffee_shop",
    "specialty_coffee",
    "coffee_bakery",
    "takeaway_coffee",
)


class TemplateService:
    def list(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for code in _TEMPLATE_CODES:
            value = self._load(code, 1)
            draft = self.draft(code, 1)
            result.append(
                {
                    "code": value["code"],
                    "version": value["version"],
                    "name": value["name"],
                    "description": value["description"],
                    "category_count": len(value["categories"]),
                    "product_count": len(value["products"]),
                    "has_draft_recipes": any(
                        entity.entity_type is ImportEntityType.RECIPE for entity in draft.entities
                    ),
                }
            )
        return result

    def draft(
        self, code: str, version: int, options: dict[str, object] | None = None
    ) -> CanonicalImportDraft:
        value = self._load(code, version)
        options = options or {}
        if code == "classic_coffee_shop":
            options = dict(options)
            if not options:
                options = {
                    "alternative_milks": ["Oat milk"],
                    "extras": ["Extra shot"],
                    "packaging": True,
                    "include_draft_recipes": True,
                }
        sizes = _unique(options.get("sizes", []))
        alternative_milks = _unique(options.get("alternative_milks", []))
        extras = _unique(options.get("extras", []))
        packaging = bool(options.get("packaging", True))
        include_recipes = bool(options.get("include_draft_recipes", False))
        entities: list[CanonicalImportEntity] = []
        product_variant_keys: dict[str, list[tuple[str, str]]] = {}
        order = 0
        for category in value["categories"]:
            entities.append(
                CanonicalImportEntity(
                    ImportEntityType.CATEGORY,
                    f"category:{category['key']}",
                    {"name": category["name"], "sort_order": order},
                    sort_order=order,
                )
            )
            order += 1
        for product in value["products"]:
            product_key = f"product:{product['key']}"
            entities.append(
                CanonicalImportEntity(
                    ImportEntityType.PRODUCT,
                    product_key,
                    {
                        "category_key": f"category:{product['category_key']}",
                        "name": product["name"],
                        "description": product.get("description"),
                        "status": "DRAFT",
                    },
                    sort_order=order,
                )
            )
            order += 1
            product_variants = product["variants"]
            if sizes and product["category_key"] != "food":
                base = product_variants[0]
                product_variants = [
                    {
                        "key": f"{product['key']}-{size.casefold()}",
                        "name": size,
                        "price_minor": base["price_minor"],
                    }
                    for size in sizes
                ]
            for variant_index, variant in enumerate(product_variants):
                variant_key = f"variant:{variant['key']}"
                product_variant_keys.setdefault(product["key"], []).append(
                    (variant_key, str(variant["name"]))
                )
                entities.append(
                    CanonicalImportEntity(
                        ImportEntityType.VARIANT,
                        variant_key,
                        {
                            "product_key": product_key,
                            "name": variant["name"],
                            "sku": variant.get("sku"),
                            "price_minor": str(variant["price_minor"]),
                            "is_default": variant_index == 0,
                            "status": "DRAFT",
                        },
                        sort_order=order,
                    )
                )
                order += 1
                modifier_options = [*alternative_milks, *extras]
                if packaging:
                    modifier_options.append("Takeaway packaging")
                if modifier_options and product["category_key"] != "food":
                    group_key = f"modifier-group:{variant['key']}:extras"
                    entities.append(
                        CanonicalImportEntity(
                            ImportEntityType.MODIFIER_GROUP,
                            group_key,
                            {
                                "variant_key": variant_key,
                                "name": "Options",
                                "selection_type": "MULTIPLE",
                                "min_selections": 0,
                                "max_selections": max(1, len(modifier_options)),
                            },
                            sort_order=order,
                        )
                    )
                    order += 1
                    for option_index, option in enumerate(dict.fromkeys(modifier_options)):
                        inventory_deltas = _modifier_deltas(
                            option,
                            variant_name=str(variant["name"]),
                            alternative_milks=alternative_milks,
                            extras=extras,
                            packaging=packaging,
                        )
                        entities.append(
                            CanonicalImportEntity(
                                ImportEntityType.MODIFIER_OPTION,
                                f"modifier-option:{variant['key']}:{option_index}",
                                {
                                    "group_key": group_key,
                                    "name": option,
                                    "price_delta_minor": "0",
                                    "inventory_deltas": inventory_deltas,
                                },
                                sort_order=order,
                            )
                        )
                        order += 1
        inventory = _inventory_options(
            include_recipes=include_recipes,
            alternative_milks=alternative_milks,
            extras=extras,
            packaging=packaging,
            sizes=sizes,
        )
        if inventory:
            for key, name, unit in inventory:
                entities.append(
                    CanonicalImportEntity(
                        ImportEntityType.INVENTORY_ITEM,
                        f"inventory:{key}",
                        {"name": name, "sku": None, "base_unit": unit},
                        sort_order=order,
                    )
                )
                order += 1
        if include_recipes:
            recipes = {
                "espresso": [("coffee-beans", "18", "g")],
                "cappuccino": [("coffee-beans", "18", "g"), ("milk", "180", "ml")],
            }
            for product_key, components in recipes.items():
                for variant_key, variant_name in product_variant_keys.get(product_key, []):
                    recipe_components = list(components)
                    size = _size_key(variant_name)
                    if packaging and size:
                        recipe_components.extend(
                            [(f"cup-{size}", "1", "pcs"), (f"lid-{size}", "1", "pcs")]
                        )
                    entities.append(
                        CanonicalImportEntity(
                            ImportEntityType.RECIPE,
                            f"recipe:{variant_key}",
                            {
                                "variant_key": variant_key,
                                "name": f"Starter {product_key} {variant_name} recipe",
                                "components": [
                                    {
                                        "inventory_item_key": f"inventory:{item}",
                                        "quantity": quantity,
                                        "unit": unit,
                                    }
                                    for item, quantity, unit in recipe_components
                                ],
                                "review_required": True,
                            },
                            warning_codes=("DRAFT_RECIPE_REVIEW_REQUIRED",),
                            sort_order=order,
                        )
                    )
                    order += 1
        return CanonicalImportDraft(str(value["code"]), value["version"], tuple(entities))

    def workbook(self) -> bytes:
        workbook = Workbook()
        workbook.remove(workbook.active)
        sheets = {
            "Products": [
                "Category",
                "Product",
                "Variant",
                "SKU",
                "Price",
                "Location",
                "Available",
                "Description",
            ],
            "Recipes": ["Product", "Variant", "Inventory Item", "Quantity", "Unit"],
            "Inventory": ["Name", "SKU", "Unit", "Opening Quantity", "Unit Cost KZT"],
            "Modifiers": [
                "Product",
                "Variant",
                "Group",
                "Selection Type",
                "Option",
                "Price Delta",
                "Inventory Item",
                "Quantity Delta",
                "Unit",
            ],
        }
        for name, headers in sheets.items():
            sheet = workbook.create_sheet(name)
            sheet.append(headers)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            sheet.freeze_panes = "A2"
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def _load(self, code: str, version: int) -> dict[str, object]:
        if code not in _TEMPLATE_CODES or version != 1:
            raise TemplateNotFound("Template or version not found")
        resource = files("beanly.modules.onboarding.templates").joinpath(f"{code}.v{version}.json")
        return json.loads(resource.read_text(encoding="utf-8"))


def _unique(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "option"


def _size_key(value: str) -> str | None:
    match = re.search(r"\d+", value)
    return match.group() if match else None


def _inventory_options(
    *,
    include_recipes: bool,
    alternative_milks: list[str],
    extras: list[str],
    packaging: bool,
    sizes: list[str],
) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    if include_recipes or any("extra shot" in value.casefold() for value in extras):
        result.append(("coffee-beans", "Coffee beans", "g"))
    if include_recipes:
        result.append(("milk", "Milk", "ml"))
    result.extend((_key(value), value, "ml") for value in alternative_milks)
    result.extend(
        (_key(value), value, "ml")
        for value in extras
        if "syrup" in value.casefold()
    )
    if packaging:
        packaging_sizes = [_size_key(value) for value in sizes] or ["250", "350", "450"]
        for size in dict.fromkeys(value for value in packaging_sizes if value):
            result.extend(
                ((f"cup-{size}", f"Cup {size}", "pcs"), (f"lid-{size}", f"Lid {size}", "pcs"))
            )
    return list(dict.fromkeys(result))


def _modifier_deltas(
    option: str,
    *,
    variant_name: str,
    alternative_milks: list[str],
    extras: list[str],
    packaging: bool,
) -> list[dict[str, str]]:
    if option in alternative_milks:
        return [
            {
                "inventory_item_key": f"inventory:{_key(option)}",
                "quantity": "180",
                "unit": "ml",
            }
        ]
    if option in extras and "extra shot" in option.casefold():
        return [{"inventory_item_key": "inventory:coffee-beans", "quantity": "18", "unit": "g"}]
    if option in extras and "syrup" in option.casefold():
        return [{"inventory_item_key": f"inventory:{_key(option)}", "quantity": "10", "unit": "ml"}]
    if option == "Takeaway packaging" and packaging:
        size = _size_key(variant_name) or "350"
        return [
            {"inventory_item_key": f"inventory:cup-{size}", "quantity": "1", "unit": "pcs"},
            {"inventory_item_key": f"inventory:lid-{size}", "quantity": "1", "unit": "pcs"},
        ]
    return []
