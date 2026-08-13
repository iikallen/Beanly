from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from beanly.modules.promotions.domain.enums import (
    ApplicationMode,
    DiscountKind,
    DiscountSource,
    PromotionScope,
    PromotionStatus,
    StackingPolicy,
    TargetRole,
    TargetType,
)


@dataclass(frozen=True, slots=True)
class PromotionTarget:
    id: UUID
    promotion_id: UUID
    role: TargetRole
    target_type: TargetType
    target_id: UUID | None
    quantity: int
    sort_order: int


@dataclass(frozen=True, slots=True)
class PromotionSchedule:
    id: UUID
    promotion_id: UUID
    weekday: int
    start_local_time: time
    end_local_time: time


@dataclass(frozen=True, slots=True)
class PromotionCode:
    id: UUID
    organization_id: UUID
    promotion_id: UUID
    code_normalized: str
    is_active: bool
    valid_from: datetime | None
    valid_to: datetime | None
    max_redemptions: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Promotion:
    id: UUID
    organization_id: UUID
    name: str
    pos_name: str
    status: PromotionStatus
    application_mode: ApplicationMode
    discount_kind: DiscountKind
    scope: PromotionScope
    percent_rate: Decimal | None
    amount_minor: int | None
    fixed_price_minor: int | None
    priority: int
    stacking_policy: StackingPolicy
    include_modifier_price: bool
    minimum_subtotal_minor: int | None
    maximum_discount_minor: int | None
    valid_from: datetime | None
    valid_to: datetime | None
    all_locations: bool
    requires_override_permission: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    location_ids: tuple[UUID, ...] = ()
    schedules: tuple[PromotionSchedule, ...] = ()
    targets: tuple[PromotionTarget, ...] = ()
    codes: tuple[PromotionCode, ...] = ()


@dataclass(frozen=True, slots=True)
class PricingItem:
    id: UUID
    category_id: UUID | None
    product_id: UUID
    variant_id: UUID
    quantity: int
    base_price_minor: int
    modifier_price_minor: int

    @property
    def unit_gross_minor(self) -> int:
        return self.base_price_minor + self.modifier_price_minor

    @property
    def gross_minor(self) -> int:
        return self.unit_gross_minor * self.quantity


@dataclass(frozen=True, slots=True)
class DiscountAllocation:
    order_item_id: UUID
    eligible_amount_minor: int
    discount_amount_minor: int
    sort_order: int


@dataclass(frozen=True, slots=True)
class AppliedDiscount:
    id: UUID
    promotion_id: UUID | None
    source: DiscountSource
    promotion_name: str
    discount_kind: DiscountKind
    scope: PromotionScope
    percent_rate: Decimal | None
    configured_amount_minor: int | None
    promo_code_snapshot: str | None
    reason: str | None
    discount_total_minor: int
    promotion_config_hash: str
    sort_order: int
    client_discount_id: UUID | None = None
    applied_by_user_id: UUID | None = None
    applied_at: datetime | None = None
    allocations: tuple[DiscountAllocation, ...] = ()


@dataclass(frozen=True, slots=True)
class PricingResult:
    subtotal_minor: int
    discount_total_minor: int
    total_minor: int
    item_discount_minor: dict[UUID, int] = field(default_factory=dict)
    discounts: tuple[AppliedDiscount, ...] = ()
    priced_at: datetime | None = None
