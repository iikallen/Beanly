from enum import StrEnum


class ProductStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RecipeCostStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ModifierSelectionType(StrEnum):
    SINGLE = "SINGLE"
    MULTIPLE = "MULTIPLE"
