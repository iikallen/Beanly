from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from beanly.modules.online_ordering.domain.enums import (
    FulfillmentTiming,
    FulfillmentType,
    OnlineOrderSource,
    OnlineOrderStatus,
    OrderingStationKind,
)

Money = Annotated[str, Field(pattern=r"^(0|[1-9]\d{0,18})$")]


class ScheduleInput(BaseModel):
    weekday: Annotated[int, Field(ge=0, le=6)]
    opens_at_local: time
    closes_at_local: time

    @model_validator(mode="after")
    def different_times(self):
        if self.opens_at_local == self.closes_at_local:
            raise ValueError("Ordering schedule cannot span exactly 24 hours")
        return self


class LocationSettingsWrite(BaseModel):
    location_id: UUID
    public_slug: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")]
    enabled: bool = False
    pickup_enabled: bool = True
    delivery_enabled: bool = False
    qr_dine_in_enabled: bool = True
    qr_auto_accept: bool = False
    register_id: UUID | None = None
    accepting_orders: bool = True
    minimum_order_minor: Money = "0"
    maximum_order_minor: Money | None = None
    guest_name_required: bool = False
    guest_phone_required_pickup: bool = True
    preparation_minutes: Annotated[int, Field(ge=0, le=240)] = 15
    slot_interval_minutes: Annotated[int, Field(ge=5, le=120)] = 15
    slot_capacity: Annotated[int, Field(ge=1, le=1000)] = 20
    max_advance_minutes: Annotated[int, Field(ge=15, le=43200)] = 10080
    cancellation_cutoff_minutes: Annotated[int, Field(ge=0, le=1440)] = 0
    delivery_minimum_order_minor: Money = "0"
    default_fulfillment_type: FulfillmentType = FulfillmentType.PICKUP
    schedules: Annotated[list[ScheduleInput], Field(max_length=28)] = []

    @model_validator(mode="after")
    def order_limits(self):
        if self.maximum_order_minor is not None and int(self.maximum_order_minor) < int(
            self.minimum_order_minor
        ):
            raise ValueError("maximum_order_minor must be at least minimum_order_minor")
        if self.pickup_enabled or self.delivery_enabled:
            if self.default_fulfillment_type == FulfillmentType.PICKUP and not self.pickup_enabled:
                raise ValueError("Default pickup fulfillment must be enabled")
            if (
                self.default_fulfillment_type == FulfillmentType.DELIVERY
                and not self.delivery_enabled
            ):
                raise ValueError("Default delivery fulfillment must be enabled")
        return self


class LocationSettingsResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    public_slug: str
    enabled: bool
    pickup_enabled: bool
    delivery_enabled: bool
    qr_dine_in_enabled: bool
    qr_auto_accept: bool
    register_id: UUID | None
    accepting_orders: bool
    manual_pause_reason: str | None
    paused_until: datetime | None
    closed_date: date | None
    minimum_order_minor: str
    maximum_order_minor: str | None
    guest_name_required: bool
    guest_phone_required_pickup: bool
    preparation_minutes: int
    slot_interval_minutes: int
    slot_capacity: int
    max_advance_minutes: int
    cancellation_cutoff_minutes: int
    delivery_minimum_order_minor: str
    default_fulfillment_type: FulfillmentType
    schedules: list[ScheduleInput]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, value):
        return cls(
            **{
                name: getattr(value, name)
                for name in cls.model_fields
                if name
                not in {
                    "minimum_order_minor",
                    "maximum_order_minor",
                    "delivery_minimum_order_minor",
                    "schedules",
                }
            },
            minimum_order_minor=str(value.minimum_order_minor),
            maximum_order_minor=(
                str(value.maximum_order_minor) if value.maximum_order_minor is not None else None
            ),
            delivery_minimum_order_minor=str(value.delivery_minimum_order_minor),
            schedules=[
                ScheduleInput(
                    weekday=item.weekday,
                    opens_at_local=item.opens_at_local,
                    closes_at_local=item.closes_at_local,
                )
                for item in sorted(
                    value.schedules,
                    key=lambda item: (item.weekday, item.opens_at_local, str(item.id)),
                )
            ],
        )


class StationCreate(BaseModel):
    location_id: UUID
    kind: OrderingStationKind
    label: Annotated[str, Field(min_length=1, max_length=100)]


class StationPatch(BaseModel):
    kind: OrderingStationKind | None = None
    label: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    is_active: bool | None = None


class StationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    kind: OrderingStationKind
    label: str
    is_active: bool
    public_token: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, value, token: str | None = None):
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            kind=value.kind,
            label=value.label,
            is_active=value.is_active,
            public_token=token,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )


class PublicOrderingResponse(BaseModel):
    slug: str
    location_id: UUID
    location_name: str
    timezone: str
    currency_code: str
    enabled: bool
    pickup_enabled: bool
    delivery_enabled: bool
    qr_dine_in_enabled: bool
    accepting_orders: bool
    unavailable_reason: str | None
    guest_name_required: bool
    guest_phone_required_pickup: bool
    station: dict[str, object] | None


class PublicMenuResponse(BaseModel):
    location_id: UUID
    currency_code: str
    categories: list[dict[str, object]]


class AvailabilityResponse(BaseModel):
    available: bool
    schedule_open: bool
    shift_open: bool
    accepting_orders: bool
    reasons: list[str]


class DeliveryZoneWrite(BaseModel):
    location_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=120)]
    enabled: bool = True
    delivery_fee_minor: Money = "0"
    minimum_order_minor: Money = "0"


class DeliveryZonePatch(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    enabled: bool | None = None
    delivery_fee_minor: Money | None = None
    minimum_order_minor: Money | None = None


class DeliveryZoneResponse(BaseModel):
    id: UUID
    location_id: UUID
    name: str
    enabled: bool
    delivery_fee_minor: str
    minimum_order_minor: str


class FulfillmentSlotResponse(BaseModel):
    starts_at: datetime
    remaining_capacity: int


class FulfillmentOptionsResponse(BaseModel):
    timezone: str
    default_fulfillment_type: FulfillmentType
    pickup_enabled: bool
    delivery_enabled: bool
    preparation_minutes: int
    slot_interval_minutes: int
    max_advance_minutes: int
    cancellation_cutoff_minutes: int
    asap_promised_at: datetime
    slots: list[FulfillmentSlotResponse]
    delivery_zones: list[DeliveryZoneResponse]


class QuoteItemRequest(BaseModel):
    client_item_id: UUID
    variant_id: UUID
    quantity: Annotated[int, Field(gt=0, le=99)] = 1
    modifier_option_ids: Annotated[list[UUID], Field(max_length=20)] = []
    note: Annotated[str | None, Field(max_length=500)] = None


class QuoteRequest(BaseModel):
    client_order_id: UUID
    station_token: Annotated[str | None, Field(min_length=20, max_length=200)] = None
    promo_code: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    items: Annotated[list[QuoteItemRequest], Field(min_length=1, max_length=50)]
    fulfillment_type: FulfillmentType = FulfillmentType.PICKUP
    fulfillment_timing: FulfillmentTiming = FulfillmentTiming.ASAP
    requested_at: datetime | None = None
    delivery_zone_id: UUID | None = None
    delivery_address: Annotated[str | None, Field(max_length=1000)] = None
    guest_instructions: Annotated[str | None, Field(max_length=1000)] = None

    @model_validator(mode="after")
    def fulfillment_shape(self):
        if self.fulfillment_timing == FulfillmentTiming.SCHEDULED:
            if self.requested_at is None:
                raise ValueError("requested_at is required for scheduled fulfillment")
            if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
                raise ValueError("requested_at must include a timezone offset")
            if self.requested_at.second or self.requested_at.microsecond:
                raise ValueError("requested_at must use minute precision")
        elif self.requested_at is not None:
            raise ValueError("requested_at is only valid for scheduled fulfillment")
        if self.fulfillment_type == FulfillmentType.DELIVERY:
            if self.delivery_zone_id is None or not (self.delivery_address or "").strip():
                raise ValueError("Delivery zone and address are required")
        elif self.delivery_zone_id is not None or self.delivery_address is not None:
            raise ValueError("Delivery fields are only valid for delivery fulfillment")
        return self


class QuoteLineResponse(BaseModel):
    client_item_id: UUID
    variant_id: UUID
    product_name: str
    variant_name: str
    quantity: int
    base_price_minor: str
    modifier_price_minor: str
    unit_price_minor: str
    subtotal_minor: str
    discount_minor: str
    total_minor: str
    modifiers: list[dict[str, object]]


class QuoteResponse(BaseModel):
    source: OnlineOrderSource
    subtotal_minor: str
    discount_minor: str
    fulfillment_fee_minor: str
    total_minor: str
    fulfillment_type: FulfillmentType
    fulfillment_timing: FulfillmentTiming
    requested_at: datetime | None
    promised_at: datetime
    delivery_zone: DeliveryZoneResponse | None
    delivery_address: str | None
    guest_instructions: str | None
    lines: list[QuoteLineResponse]
    applied_promotions: list[dict[str, object]]
    quote_revision: str
    expires_at: datetime


class SubmitOrderRequest(QuoteRequest):
    quote_revision: Annotated[str, Field(min_length=66, max_length=96)]
    guest_name: Annotated[str | None, Field(max_length=201)] = None
    guest_phone: Annotated[str | None, Field(max_length=32)] = None


class OnlineOrderItemResponse(BaseModel):
    product_name: str
    variant_name: str
    quantity: int
    note: str | None
    unit_price_minor: str
    total_minor: str
    modifiers: list[str]


class OnlineOrderResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    sales_order_id: UUID
    order_number: int
    station_id: UUID | None
    client_order_id: UUID
    source: OnlineOrderSource
    status: OnlineOrderStatus
    guest_name: str | None
    guest_phone: str | None
    station_label: str | None
    currency_code: str
    subtotal_minor: str
    discount_minor: str
    fulfillment_fee_minor: str
    total_minor: str
    fulfillment_type: FulfillmentType
    fulfillment_timing: FulfillmentTiming
    requested_at: datetime | None
    promised_at: datetime
    delivery_zone: DeliveryZoneResponse | None
    delivery_address: str | None
    guest_instructions: str | None
    cancellation_deadline: datetime | None
    can_cancel: bool
    age_seconds: int
    kitchen_ticket_id: UUID | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    paid_at: datetime | None
    preparing_at: datetime | None
    ready_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[OnlineOrderItemResponse]
    status_token: str | None = None


class PublicOrderStatusResponse(BaseModel):
    order_number: int
    source: OnlineOrderSource
    status: OnlineOrderStatus
    station_label: str | None
    currency_code: str
    subtotal_minor: str
    discount_minor: str
    fulfillment_fee_minor: str
    total_minor: str
    fulfillment_type: FulfillmentType
    fulfillment_timing: FulfillmentTiming
    requested_at: datetime | None
    promised_at: datetime
    delivery_zone: DeliveryZoneResponse | None
    delivery_address: str | None
    guest_instructions: str | None
    cancellation_deadline: datetime | None
    can_cancel: bool
    rejection_reason: str | None
    cancel_reason: str | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    cancelled_at: datetime | None
    paid_at: datetime | None
    preparing_at: datetime | None
    ready_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[OnlineOrderItemResponse]

    @classmethod
    def from_order(cls, value: OnlineOrderResponse):
        return cls(**{name: getattr(value, name) for name in cls.model_fields})


class PublicOrderCreatedResponse(PublicOrderStatusResponse):
    status_token: str

    @classmethod
    def from_order(cls, value: OnlineOrderResponse):
        if value.status_token is None:
            raise ValueError("Public order status token is missing")
        return cls(
            **{name: getattr(value, name) for name in PublicOrderStatusResponse.model_fields},
            status_token=value.status_token,
        )


class StaffActionRequest(BaseModel):
    client_action_id: UUID
    reason: Annotated[str | None, Field(max_length=1000)] = None
    external_refund_confirmed: bool = False
    refund_reference: Annotated[str | None, Field(max_length=200)] = None


class PauseRequest(BaseModel):
    location_id: UUID
    minutes: Annotated[int | None, Field(gt=0, le=1440)] = None
    closed_today: bool = False
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def pause_mode(self):
        if self.closed_today and self.minutes is not None:
            raise ValueError("closed_today cannot be combined with minutes")
        return self


class ResumeRequest(BaseModel):
    location_id: UUID


class ReadinessResponse(BaseModel):
    ready: bool
    menu_ready: bool
    register_configured: bool
    shift_open: bool
    schedule_open: bool
    default_location_available: bool
    reasons: list[str]


class ChannelReportRow(BaseModel):
    order_source: str
    orders_count: int
    gross_sales_minor: str
    refunds_minor: str
    net_revenue_minor: str
    average_order_value_minor: str
    acceptance_rate_percent: str | None
    reject_rate_percent: str | None
