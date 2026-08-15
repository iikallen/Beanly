from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from beanly.modules.reservations.domain.enums import (
    DiningTableState,
    ReservationSource,
    ReservationStatus,
    WaitlistStatus,
)


class ReservationScheduleInput(BaseModel):
    weekday: Annotated[int, Field(ge=0, le=6)]
    opens_at_local: time
    closes_at_local: time

    @model_validator(mode="after")
    def different_times(self):
        if self.opens_at_local == self.closes_at_local:
            raise ValueError("Reservation schedule cannot span exactly 24 hours")
        return self


class ReservationSettingsWrite(BaseModel):
    location_id: UUID
    public_slug: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")]
    reservations_enabled: bool = False
    default_duration_minutes: Annotated[int, Field(ge=15, le=480)] = 90
    cleanup_buffer_minutes: Annotated[int, Field(ge=0, le=240)] = 15
    minimum_lead_minutes: Annotated[int, Field(ge=0, le=43200)] = 60
    maximum_advance_days: Annotated[int, Field(ge=1, le=365)] = 30
    guest_cancellation_cutoff_minutes: Annotated[int, Field(ge=0, le=10080)] = 120
    maximum_party_size: Annotated[int, Field(ge=1, le=1000)] = 12
    slot_interval_minutes: Annotated[int, Field(ge=5, le=120)] = 15
    schedules: Annotated[list[ReservationScheduleInput], Field(max_length=28)] = []


class ReservationSettingsResponse(ReservationSettingsWrite):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, value):
        return cls(
            **{name: getattr(value, name) for name in cls.model_fields if name != "schedules"},
            schedules=[
                ReservationScheduleInput.model_validate(item, from_attributes=True)
                for item in sorted(
                    value.schedules,
                    key=lambda item: (item.weekday, item.opens_at_local, str(item.id)),
                )
            ],
        )


class PublicReservationLocationResponse(BaseModel):
    slug: str
    organization_name: str
    location_name: str
    timezone: str
    reservations_enabled: bool
    minimum_lead_minutes: int
    maximum_advance_days: int
    maximum_party_size: int
    slot_interval_minutes: int


class AvailabilitySlotResponse(BaseModel):
    start_at: datetime
    end_at: datetime


class ReservationAvailabilityResponse(BaseModel):
    timezone: str
    date: date
    party_size: int
    slots: list[AvailabilitySlotResponse]


class GuestReservationCreate(BaseModel):
    client_reservation_id: UUID
    start_at: datetime
    party_size: Annotated[int, Field(gt=0, le=1000)]
    guest_name: Annotated[str, Field(min_length=1, max_length=201)]
    guest_phone: Annotated[str | None, Field(max_length=32)] = None
    guest_email: EmailStr | None = None
    guest_notes: Annotated[str | None, Field(max_length=2000)] = None

    @model_validator(mode="after")
    def aware_minute(self):
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("start_at must include a timezone offset")
        if self.start_at.second or self.start_at.microsecond:
            raise ValueError("start_at must use minute precision")
        return self


class StaffReservationCreate(GuestReservationCreate):
    location_id: UUID
    dining_table_id: UUID | None = None
    internal_notes: Annotated[str | None, Field(max_length=4000)] = None


class PublicReservationResponse(BaseModel):
    organization_name: str
    location_name: str
    timezone: str
    status: ReservationStatus
    guest_name: str
    guest_phone: str | None
    guest_email: str | None
    party_size: int
    start_at: datetime
    end_at: datetime
    guest_notes: str | None
    can_cancel: bool
    cancelled_at: datetime | None
    seated_at: datetime | None
    completed_at: datetime | None
    no_show_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GuestReservationCreatedResponse(PublicReservationResponse):
    guest_access_token: str


class ReservationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    dining_table_id: UUID
    table_name: str
    status: ReservationStatus
    source: ReservationSource
    guest_name: str
    guest_phone: str | None
    guest_email: str | None
    party_size: int
    start_at: datetime
    end_at: datetime
    guest_notes: str | None
    internal_notes: str | None
    cancelled_at: datetime | None
    seated_at: datetime | None
    completed_at: datetime | None
    no_show_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StaffActionRequest(BaseModel):
    client_action_id: UUID
    reason: Annotated[str | None, Field(max_length=1000)] = None


class SeatRequest(BaseModel):
    client_action_id: UUID
    dining_table_id: UUID | None = None


class DiningSectionCreate(BaseModel):
    location_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=120)]
    sort_order: int = 0


class DiningSectionPatch(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    sort_order: int | None = None
    is_active: bool | None = None


class DiningSectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DiningTableCreate(BaseModel):
    location_id: UUID
    section_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=100)]
    capacity: Annotated[int, Field(gt=0, le=1000)]
    sort_order: int = 0


class DiningTablePatch(BaseModel):
    section_id: UUID | None = None
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    capacity: Annotated[int | None, Field(gt=0, le=1000)] = None
    sort_order: int | None = None
    is_active: bool | None = None


class DiningTableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    section_id: UUID
    name: str
    capacity: int
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WaitlistCreate(BaseModel):
    client_entry_id: UUID
    location_id: UUID
    guest_name: Annotated[str, Field(min_length=1, max_length=201)]
    guest_phone: Annotated[str | None, Field(max_length=32)] = None
    guest_email: EmailStr | None = None
    party_size: Annotated[int, Field(gt=0, le=1000)]
    quoted_wait_minutes: Annotated[int | None, Field(ge=0, le=10080)] = None
    guest_notes: Annotated[str | None, Field(max_length=2000)] = None


class WaitlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    guest_name: str
    guest_phone: str | None
    guest_email: str | None
    party_size: int
    quoted_wait_minutes: int | None
    status: WaitlistStatus
    guest_notes: str | None
    cancelled_at: datetime | None
    seated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DirectVisitCreate(BaseModel):
    client_action_id: UUID
    location_id: UUID
    dining_table_id: UUID
    party_size: Annotated[int, Field(gt=0, le=1000)]


class OpenCheckRequest(BaseModel):
    client_order_id: UUID
    shift_id: UUID


class DiningVisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    dining_table_id: UUID
    reservation_id: UUID | None
    waitlist_entry_id: UUID | None
    sales_order_id: UUID | None
    sales_order_status: str | None = None
    party_size: int
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FloorTableResponse(BaseModel):
    id: UUID
    name: str
    capacity: int
    sort_order: int
    is_active: bool
    state: DiningTableState
    reservation: ReservationResponse | None
    visit: DiningVisitResponse | None


class FloorSectionResponse(BaseModel):
    id: UUID
    name: str
    sort_order: int
    tables: list[FloorTableResponse]


class DiningFloorResponse(BaseModel):
    location_id: UUID
    timezone: str
    sections: list[FloorSectionResponse]
