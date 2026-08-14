from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from beanly.modules.kitchen.domain.enums import (
    KitchenRoutingScope,
    KitchenStationRole,
    KitchenTicketStatus,
    KitchenWorkStatus,
)


def _utc(value: datetime) -> datetime:
    from datetime import UTC

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class StationCreate(BaseModel):
    location_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=100)]
    code: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]
    role: KitchenStationRole
    warning_after_seconds: Annotated[int, Field(gt=0, le=86400)] = 600
    late_after_seconds: Annotated[int, Field(gt=0, le=86400)] = 900
    sort_order: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def thresholds(self):
        if self.late_after_seconds <= self.warning_after_seconds:
            raise ValueError("late_after_seconds must exceed warning_after_seconds")
        return self


class StationPatch(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    code: Annotated[str | None, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")] = (
        None
    )
    role: KitchenStationRole | None = None
    is_active: bool | None = None
    warning_after_seconds: Annotated[int | None, Field(gt=0, le=86400)] = None
    late_after_seconds: Annotated[int | None, Field(gt=0, le=86400)] = None
    sort_order: Annotated[int | None, Field(ge=0)] = None

    @model_validator(mode="after")
    def thresholds(self):
        if (
            self.warning_after_seconds is not None
            and self.late_after_seconds is not None
            and self.late_after_seconds <= self.warning_after_seconds
        ):
            raise ValueError("late_after_seconds must exceed warning_after_seconds")
        return self


class StationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    name: str
    code: str
    role: KitchenStationRole
    is_default: bool
    is_active: bool
    warning_after_seconds: int
    late_after_seconds: int
    sort_order: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, value):
        return cls.model_validate(value, from_attributes=True)


class RoutingCreate(BaseModel):
    location_id: UUID
    station_id: UUID
    scope: KitchenRoutingScope
    category_id: UUID | None = None
    variant_id: UUID | None = None
    order_type: Annotated[str | None, Field(pattern=r"^(DINE_IN|TAKEAWAY|DELIVERY)$")] = None
    priority: int = 0

    @model_validator(mode="after")
    def target(self):
        if self.scope == KitchenRoutingScope.CATEGORY:
            valid = self.category_id is not None and self.variant_id is None
        else:
            valid = self.variant_id is not None and self.category_id is None
        if not valid:
            raise ValueError("Routing scope requires exactly its matching target")
        return self


class RoutingResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    station_id: UUID
    scope: KitchenRoutingScope
    category_id: UUID | None
    variant_id: UUID | None
    order_type: str | None
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, value):
        return cls.model_validate(value, from_attributes=True)


class WorkItemResponse(BaseModel):
    id: UUID
    ticket_id: UUID
    ticket_item_id: UUID
    station_id: UUID
    status: KitchenWorkStatus
    started_at: datetime | None
    ready_at: datetime | None

    @classmethod
    def from_model(cls, value):
        return cls.model_validate(value, from_attributes=True)


class TicketModifierResponse(BaseModel):
    modifier_group_id: UUID
    modifier_group_name: str
    modifier_option_id: UUID
    modifier_option_name: str
    sort_order: int

    @classmethod
    def from_model(cls, value):
        return cls.model_validate(value, from_attributes=True)


class TicketItemResponse(BaseModel):
    id: UUID
    order_item_id: UUID
    product_id: UUID
    variant_id: UUID
    product_name: str
    variant_name: str
    quantity: int
    note: str | None
    sort_order: int
    modifiers: list[TicketModifierResponse]
    work_items: list[WorkItemResponse]

    @classmethod
    def from_model(cls, value, *, station_id: UUID | None = None):
        work = value.work_items
        if station_id is not None:
            work = [item for item in work if item.station_id == station_id]
        return cls(
            **{
                name: getattr(value, name)
                for name in (
                    "id",
                    "order_item_id",
                    "product_id",
                    "variant_id",
                    "product_name",
                    "variant_name",
                    "quantity",
                    "note",
                    "sort_order",
                )
            },
            modifiers=[TicketModifierResponse.from_model(item) for item in value.modifiers],
            work_items=[WorkItemResponse.from_model(item) for item in work],
        )


class TicketResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    order_id: UUID
    payment_id: UUID
    shift_id: UUID
    order_number: int
    order_type: str
    customer_id: UUID | None
    customer_name: str | None
    customer_phone: str | None
    table_label: str | None
    guest_count: int | None
    note: str | None
    status: KitchenTicketStatus
    ordered_at: datetime
    fired_at: datetime
    started_at: datetime | None
    ready_at: datetime | None
    completed_at: datetime | None
    version: int
    offline_delayed: bool
    items: list[TicketItemResponse]

    @classmethod
    def from_model(cls, value, *, station_id: UUID | None = None, whole_order: bool = True):
        items = value.items
        if not whole_order and station_id is not None:
            items = [
                item
                for item in items
                if any(work.station_id == station_id for work in item.work_items)
            ]
        scalar_fields = tuple(
            name for name in cls.model_fields if name not in {"items", "offline_delayed"}
        )
        return cls(
            **{name: getattr(value, name) for name in scalar_fields},
            offline_delayed=(_utc(value.fired_at) - _utc(value.ordered_at)).total_seconds() >= 60,
            items=[
                TicketItemResponse.from_model(item, station_id=None if whole_order else station_id)
                for item in sorted(items, key=lambda item: item.sort_order)
            ],
        )


class BoardResponse(BaseModel):
    station: StationResponse
    cursor: int
    server_time: datetime
    tickets: list[TicketResponse]


class ActionRequest(BaseModel):
    client_action_id: UUID


class ReadinessResponse(BaseModel):
    ready: bool
    active_stations: int
    default_station: StationResponse | None
    unrouted_variants: list[UUID]


class PerformanceRow(BaseModel):
    location_id: UUID
    station_id: UUID
    station_name: str
    completed_count: int
    average_seconds: float
    p50_seconds: float
    p95_seconds: float
    late_percent: float
