from enum import StrEnum


class ProductGroupBy(StrEnum):
    PRODUCT = "PRODUCT"
    VARIANT = "VARIANT"


class ProductSort(StrEnum):
    REVENUE = "REVENUE"
    QUANTITY = "QUANTITY"
    GROSS_PROFIT = "GROSS_PROFIT"


class ABCClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class MenuEngineeringClass(StrEnum):
    HERO = "HERO"
    WORKHORSE = "WORKHORSE"
    PUZZLE = "PUZZLE"
    LOW_PERFORMER = "LOW_PERFORMER"


class HourMetric(StrEnum):
    REVENUE = "REVENUE"
    ORDERS = "ORDERS"
    ITEMS = "ITEMS"
