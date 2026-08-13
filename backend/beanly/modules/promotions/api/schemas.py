from datetime import datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.promotions.domain.entities import Promotion
from beanly.modules.promotions.domain.enums import (
    ApplicationMode,
    DiscountKind,
    PromotionScope,
    PromotionStatus,
    StackingPolicy,
    TargetRole,
    TargetType,
)


class ScheduleInput(BaseModel):
    weekday: Annotated[int, Field(ge=0, le=6)]
    start_local_time: time
    end_local_time: time


class TargetInput(BaseModel):
    role: TargetRole = TargetRole.ELIGIBLE
    target_type: TargetType
    target_id: UUID | None = None
    quantity: Annotated[int, Field(gt=0)] = 1
    sort_order: Annotated[int, Field(ge=0)] = 0


class PromotionWrite(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    pos_name: Annotated[str, Field(min_length=1, max_length=100)]
    application_mode: ApplicationMode
    discount_kind: DiscountKind
    scope: PromotionScope
    percent_rate: Annotated[Decimal | None, Field(gt=0, le=100)] = None
    amount_minor: Annotated[int | None, Field(ge=0, le=MAX_NUMERIC_20_6_MINOR)] = None
    fixed_price_minor: Annotated[int | None, Field(ge=0, le=MAX_NUMERIC_20_6_MINOR)] = None
    priority: int = 0
    stacking_policy: StackingPolicy = StackingPolicy.EXCLUSIVE
    include_modifier_price: bool = False
    minimum_subtotal_minor: Annotated[int | None, Field(ge=0, le=MAX_NUMERIC_20_6_MINOR)] = None
    maximum_discount_minor: Annotated[int | None, Field(ge=0, le=MAX_NUMERIC_20_6_MINOR)] = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    all_locations: bool = True
    requires_override_permission: bool = False
    location_ids: list[UUID] = []
    schedules: list[ScheduleInput] = []
    targets: list[TargetInput] = []

    @model_validator(mode="after")
    def validate_rule(self):
        field = {
            DiscountKind.PERCENT: self.percent_rate,
            DiscountKind.FIXED_AMOUNT: self.amount_minor,
            DiscountKind.FIXED_PRICE: self.fixed_price_minor,
        }.get(self.discount_kind)
        if self.discount_kind != DiscountKind.BOGO and field is None:
            raise ValueError("Selected discount kind requires its value")
        values = (self.percent_rate, self.amount_minor, self.fixed_price_minor)
        expected_values = 0 if self.discount_kind == DiscountKind.BOGO else 1
        if sum(value is not None for value in values) != expected_values:
            raise ValueError("Only the selected discount value may be set")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        if not self.all_locations and not self.location_ids:
            raise ValueError("location_ids are required when all_locations is false")
        if any(value.start_local_time >= value.end_local_time for value in self.schedules):
            raise ValueError("schedule start must be before end")
        if any(
            (value.target_type == TargetType.ALL) != (value.target_id is None)
            for value in self.targets
        ):
            raise ValueError("ALL target must omit target_id; other targets require it")
        roles = {value.role for value in self.targets}
        if self.discount_kind == DiscountKind.BOGO:
            if self.scope != PromotionScope.ITEM or not {TargetRole.BUY, TargetRole.GET} <= roles:
                raise ValueError("BOGO requires ITEM scope with BUY and GET targets")
        elif self.scope == PromotionScope.COMBO:
            if self.discount_kind != DiscountKind.FIXED_PRICE or sum(
                value.role == TargetRole.COMBO_COMPONENT for value in self.targets
            ) < 2:
                raise ValueError("COMBO requires FIXED_PRICE and at least two components")
        elif self.scope == PromotionScope.ITEM and TargetRole.ELIGIBLE not in roles:
            raise ValueError("ITEM promotion requires an ELIGIBLE target")
        return self


class PromotionPatch(PromotionWrite):
    pass


class PromotionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    pos_name: str
    status: PromotionStatus
    application_mode: ApplicationMode
    discount_kind: DiscountKind
    scope: PromotionScope
    percent_rate: Decimal | None
    amount_minor: str | None
    fixed_price_minor: str | None
    priority: int
    stacking_policy: StackingPolicy
    include_modifier_price: bool
    minimum_subtotal_minor: str | None
    maximum_discount_minor: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    all_locations: bool
    requires_override_permission: bool
    location_ids: list[UUID]
    schedules: list[ScheduleInput]
    targets: list[TargetInput]
    codes: list[dict[str, object]]
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, value: Promotion):
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            name=value.name,
            pos_name=value.pos_name,
            status=value.status,
            application_mode=value.application_mode,
            discount_kind=value.discount_kind,
            scope=value.scope,
            percent_rate=value.percent_rate,
            amount_minor=str(value.amount_minor) if value.amount_minor is not None else None,
            fixed_price_minor=str(value.fixed_price_minor)
            if value.fixed_price_minor is not None
            else None,
            priority=value.priority,
            stacking_policy=value.stacking_policy,
            include_modifier_price=value.include_modifier_price,
            minimum_subtotal_minor=str(value.minimum_subtotal_minor)
            if value.minimum_subtotal_minor is not None
            else None,
            maximum_discount_minor=str(value.maximum_discount_minor)
            if value.maximum_discount_minor is not None
            else None,
            valid_from=value.valid_from,
            valid_to=value.valid_to,
            all_locations=value.all_locations,
            requires_override_permission=value.requires_override_permission,
            location_ids=list(value.location_ids),
            schedules=[
                ScheduleInput(
                    weekday=x.weekday,
                    start_local_time=x.start_local_time,
                    end_local_time=x.end_local_time,
                )
                for x in value.schedules
            ],
            targets=[
                TargetInput(
                    role=x.role,
                    target_type=x.target_type,
                    target_id=x.target_id,
                    quantity=x.quantity,
                    sort_order=x.sort_order,
                )
                for x in value.targets
            ],
            codes=[
                {
                    "id": x.id,
                    "code": x.code_normalized,
                    "is_active": x.is_active,
                    "valid_from": x.valid_from,
                    "valid_to": x.valid_to,
                    "max_redemptions": x.max_redemptions,
                }
                for x in value.codes
            ],
            created_by=value.created_by,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class PromotionPerformanceResponse(BaseModel):
    promotion_id: UUID
    promotion_name: str
    orders_count: int
    applications_count: int
    items_count: int
    gross_eligible_amount: str
    discount_amount: str
    net_revenue_amount: str
    refund_amount: str


class CodeCreate(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=80)]
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    max_redemptions: Annotated[int | None, Field(gt=0)] = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class ManualDiscountRequest(BaseModel):
    client_discount_id: UUID
    promotion_id: UUID


class CodeDiscountRequest(BaseModel):
    client_discount_id: UUID
    code: Annotated[str, Field(min_length=1, max_length=80)]


class CustomDiscountRequest(BaseModel):
    client_discount_id: UUID
    type: DiscountKind
    percent: Annotated[Decimal | None, Field(gt=0, le=100)] = None
    amount_minor: Annotated[int | None, Field(gt=0, le=MAX_NUMERIC_20_6_MINOR)] = None
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def custom_kind(self):
        if self.type == DiscountKind.PERCENT and self.percent is not None:
            return self
        if self.type == DiscountKind.FIXED_AMOUNT and self.amount_minor is not None:
            return self
        raise ValueError("Custom discount must be PERCENT or FIXED_AMOUNT with a value")


class PreviewItem(BaseModel):
    id: UUID
    category_id: UUID | None = None
    product_id: UUID
    variant_id: UUID
    quantity: Annotated[int, Field(gt=0)] = 1
    base_price_minor: Annotated[int, Field(ge=0)]
    modifier_price_minor: Annotated[int, Field(ge=0)] = 0


class PromotionPreviewRequest(BaseModel):
    location_id: UUID
    occurred_at: datetime
    items: list[PreviewItem]


class PromotionPreviewResponse(BaseModel):
    subtotal_minor: str
    discount_total_minor: str
    total_minor: str
    item_discount_minor: dict[UUID, str]
