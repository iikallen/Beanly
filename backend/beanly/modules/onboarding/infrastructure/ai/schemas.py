import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.onboarding.application.dto import (
    CanonicalImportDraft,
    CanonicalImportEntity,
)
from beanly.modules.onboarding.domain.enums import ImportEntityType
from beanly.modules.onboarding.domain.exceptions import AiExtractionFailed


class ExtractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExtractedModifierOption(ExtractionModel):
    name: str = Field(min_length=1, max_length=150)
    price_delta_minor: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("price_delta_minor")
    @classmethod
    def validate_price_delta(cls, value: int) -> int:
        return _bounded_minor(value)


class ExtractedModifierGroup(ExtractionModel):
    name: str = Field(min_length=1, max_length=150)
    selection_type: Literal["SINGLE", "MULTIPLE"]
    min_selections: int = Field(default=0, ge=0, le=100)
    max_selections: int = Field(default=1, ge=1, le=100)
    options: list[ExtractedModifierOption] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @model_validator(mode="after")
    def valid_selection(self) -> "ExtractedModifierGroup":
        if self.min_selections > self.max_selections:
            raise ValueError("min_selections cannot exceed max_selections")
        if self.selection_type == "SINGLE" and self.max_selections != 1:
            raise ValueError("SINGLE modifier groups must have max_selections=1")
        _require_unique_names(self.options, "modifier option")
        return self


class ExtractedVariant(ExtractionModel):
    name: str = Field(min_length=1, max_length=150)
    price_minor: int = Field(ge=0)
    modifiers: list[ExtractedModifierGroup] = Field(default_factory=list, max_length=50)
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("price_minor")
    @classmethod
    def validate_price(cls, value: int) -> int:
        return _bounded_minor(value)

    @model_validator(mode="after")
    def unique_modifiers(self) -> "ExtractedVariant":
        _require_unique_names(self.modifiers, "modifier group")
        return self


class ExtractedProduct(ExtractionModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    variants: list[ExtractedVariant] = Field(min_length=1, max_length=50)
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def unique_variants(self) -> "ExtractedProduct":
        _require_unique_names(self.variants, "variant")
        return self


class ExtractedCategory(ExtractionModel):
    name: str = Field(min_length=1, max_length=150)
    products: list[ExtractedProduct] = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)
    source_reference: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @model_validator(mode="after")
    def unique_products(self) -> "ExtractedCategory":
        _require_unique_names(self.products, "product")
        return self


class MenuExtractionDocument(ExtractionModel):
    currency_code: Literal["KZT"]
    categories: list[ExtractedCategory] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_categories(self) -> "MenuExtractionDocument":
        _require_unique_names(self.categories, "category")
        return self


def to_canonical_draft(
    document: MenuExtractionDocument,
    *,
    confidence_threshold: float,
) -> CanonicalImportDraft:
    entities: list[CanonicalImportEntity] = []
    order = 0
    for category_index, category in enumerate(document.categories):
        category_key = f"ai:category:{category_index}:{_slug(category.name)}"
        entities.append(
            CanonicalImportEntity(
                ImportEntityType.CATEGORY,
                category_key,
                {
                    "name": category.name,
                    "sort_order": category_index,
                    "extraction": _evidence(category.confidence, category.source_reference),
                },
                warning_codes=_warnings(category.confidence, confidence_threshold),
                sort_order=order,
            )
        )
        order += 1
        for product_index, product in enumerate(category.products):
            product_key = (
                f"ai:product:{category_index}:{product_index}:{_slug(product.name)}"
            )
            entities.append(
                CanonicalImportEntity(
                    ImportEntityType.PRODUCT,
                    product_key,
                    {
                        "category_key": category_key,
                        "name": product.name,
                        "description": product.description,
                        "status": "DRAFT",
                        "extraction": _evidence(
                            product.confidence, product.source_reference
                        ),
                    },
                    warning_codes=_warnings(product.confidence, confidence_threshold),
                    sort_order=order,
                )
            )
            order += 1
            for variant_index, variant in enumerate(product.variants):
                variant_key = (
                    f"ai:variant:{category_index}:{product_index}:{variant_index}:"
                    f"{_slug(variant.name)}"
                )
                entities.append(
                    CanonicalImportEntity(
                        ImportEntityType.VARIANT,
                        variant_key,
                        {
                            "product_key": product_key,
                            "name": variant.name,
                            "sku": None,
                            "price_minor": str(variant.price_minor),
                            "is_default": variant_index == 0,
                            "status": "DRAFT",
                            "extraction": _evidence(
                                variant.confidence, variant.source_reference
                            ),
                        },
                        warning_codes=_warnings(
                            variant.confidence, confidence_threshold
                        ),
                        sort_order=order,
                    )
                )
                order += 1
                for group_index, group in enumerate(variant.modifiers):
                    group_key = (
                        f"ai:modifier-group:{category_index}:{product_index}:"
                        f"{variant_index}:{group_index}:{_slug(group.name)}"
                    )
                    entities.append(
                        CanonicalImportEntity(
                            ImportEntityType.MODIFIER_GROUP,
                            group_key,
                            {
                                "variant_key": variant_key,
                                "name": group.name,
                                "selection_type": group.selection_type,
                                "min_selections": group.min_selections,
                                "max_selections": group.max_selections,
                                "extraction": _evidence(
                                    group.confidence, group.source_reference
                                ),
                            },
                            warning_codes=_warnings(
                                group.confidence, confidence_threshold
                            ),
                            sort_order=order,
                        )
                    )
                    order += 1
                    for option_index, option in enumerate(group.options):
                        option_key = (
                            f"ai:modifier-option:{category_index}:{product_index}:"
                            f"{variant_index}:{group_index}:{option_index}:"
                            f"{_slug(option.name)}"
                        )
                        entities.append(
                            CanonicalImportEntity(
                                ImportEntityType.MODIFIER_OPTION,
                                option_key,
                                {
                                    "group_key": group_key,
                                    "name": option.name,
                                    "price_delta_minor": str(
                                        option.price_delta_minor
                                    ),
                                    "inventory_deltas": [],
                                    "extraction": _evidence(
                                        option.confidence,
                                        option.source_reference,
                                    ),
                                },
                                warning_codes=_warnings(
                                    option.confidence, confidence_threshold
                                ),
                                sort_order=order,
                            )
                        )
                        order += 1
    if len(entities) > 10_000:
        raise AiExtractionFailed("AI extraction exceeds the 10000 entity limit")
    return CanonicalImportDraft("local_vision", 1, tuple(entities))


def _clean_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Name cannot be blank")
    if normalized[0] in "=+-@\t\r\n":
        normalized = f"'{normalized}"
    return normalized


def _bounded_minor(value: int) -> int:
    if value > MAX_NUMERIC_20_6_MINOR:
        raise ValueError("Money amount exceeds the supported range")
    return value


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9а-яё]+", "-", value.casefold()).strip("-")
    return normalized[:80] or "item"


def _evidence(confidence: float, source_reference: str | None) -> dict[str, object]:
    return {"confidence": confidence, "source_reference": source_reference}


def _warnings(confidence: float, threshold: float) -> tuple[str, ...]:
    return ("AI_LOW_CONFIDENCE",) if confidence < threshold else ()


def _require_unique_names(values, label: str) -> None:
    names = [value.name.casefold() for value in values]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate {label} names are not allowed")
