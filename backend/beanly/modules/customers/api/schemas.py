from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    phone: Annotated[str, Field(min_length=3, max_length=32)]
    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    email: Annotated[str | None, Field(max_length=320)] = None
    birth_date: date | None = None
    note: Annotated[str | None, Field(max_length=4000)] = None
    marketing_consent: bool = False


class CustomerPatch(BaseModel):
    phone: Annotated[str | None, Field(min_length=3, max_length=32)] = None
    first_name: Annotated[str | None, Field(max_length=100)] = None
    last_name: Annotated[str | None, Field(max_length=100)] = None
    email: Annotated[str | None, Field(max_length=320)] = None
    birth_date: date | None = None
    note: Annotated[str | None, Field(max_length=4000)] = None
    marketing_consent: bool | None = None


class CustomerTier(BaseModel):
    id: UUID
    name: str


class CustomerResponse(BaseModel):
    id: UUID
    organization_id: UUID
    phone: str
    first_name: str | None
    last_name: str | None
    email: str | None
    birth_date: date | None
    note: str | None
    marketing_consent: bool
    visit_count: int
    lifetime_value_minor: str
    last_visit_at: datetime | None
    loyalty_points_balance: str
    tier: CustomerTier | None
    created_at: datetime
    updated_at: datetime


class CustomerOrderResponse(BaseModel):
    id: UUID
    location_id: UUID
    number: str
    status: str
    total_minor: str
    refunded_minor: str
    net_minor: str
    paid_at: datetime | None


class LoyaltyLedgerEntryResponse(BaseModel):
    id: UUID
    points_delta: str
    kind: str
    source_type: str
    source_id: str
    related_source_id: str | None
    reason: str | None
    occurred_at: datetime


class LoyaltyResponse(BaseModel):
    customer_id: UUID
    points_balance: str
    available_points: str
    lifetime_earned_points: str
    point_value_minor: str
    earn_rate_bps: int
    tier: CustomerTier | None
    entries: list[LoyaltyLedgerEntryResponse]


class LoyaltyProgramResponse(BaseModel):
    earn_rate_bps: int
    point_value_minor: str
    birthday_reward_points: str
    is_active: bool


class LoyaltyProgramPatch(BaseModel):
    earn_rate_bps: Annotated[int, Field(ge=0, le=10000)]
    point_value_minor: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
    birthday_reward_points: Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,18})$")] = "0"
    is_active: bool = True


class LoyaltyTierWrite(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    threshold_lifetime_points: Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,18})$")]
    earn_multiplier_bps: Annotated[int, Field(ge=0, le=100000)] = 10000


class LoyaltyTierResponse(LoyaltyTierWrite):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


class LoyaltyAdjustmentRequest(BaseModel):
    client_adjustment_id: UUID
    points_delta: Annotated[str, Field(pattern=r"^-?[1-9][0-9]{0,18}$")]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class CustomerAttachRequest(BaseModel):
    customer_id: UUID | None


class LoyaltyQuoteRequest(BaseModel):
    points: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class LoyaltyQuoteResponse(BaseModel):
    points: str
    discount_minor: str
    balance_points: str


class LoyaltyRedeemRequest(LoyaltyQuoteRequest):
    client_redemption_id: UUID


class PromotionAudienceWrite(BaseModel):
    kind: Literal["ALL", "CUSTOMER", "TIER", "BIRTHDAY"]
    tier_id: UUID | None = None
    customer_ids: Annotated[list[UUID], Field(max_length=1000)] = Field(default_factory=list)


class PromotionAudienceResponse(PromotionAudienceWrite):
    promotion_id: UUID
