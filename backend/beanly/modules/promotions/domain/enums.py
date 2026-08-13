from enum import StrEnum


class PromotionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ApplicationMode(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    CODE = "CODE"


class DiscountKind(StrEnum):
    PERCENT = "PERCENT"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    FIXED_PRICE = "FIXED_PRICE"
    BOGO = "BOGO"


class PromotionScope(StrEnum):
    ORDER = "ORDER"
    ITEM = "ITEM"
    COMBO = "COMBO"


class StackingPolicy(StrEnum):
    EXCLUSIVE = "EXCLUSIVE"
    STACKABLE = "STACKABLE"


class TargetRole(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    BUY = "BUY"
    GET = "GET"
    COMBO_COMPONENT = "COMBO_COMPONENT"


class TargetType(StrEnum):
    CATEGORY = "CATEGORY"
    PRODUCT = "PRODUCT"
    VARIANT = "VARIANT"
    ALL = "ALL"


class DiscountSource(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    PROMO_CODE = "PROMO_CODE"
    CUSTOM = "CUSTOM"
