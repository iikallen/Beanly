from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.sales.domain.enums import OrderType


class DevicePairRequest(BaseModel):
    register_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=150)]


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    register_id: UUID
    name: str
    status: str
    last_seen_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class SessionStartRequest(BaseModel):
    shift_id: UUID


class CatalogSnapshotResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    payload_hash: str
    payload: dict[str, object]


class OfflineSessionResponse(BaseModel):
    id: UUID
    device_id: UUID
    organization_id: UUID
    location_id: UUID
    register_id: UUID
    shift_id: UUID
    warehouse_id: UUID
    actor_user_id: UUID
    catalog_snapshot_id: UUID
    status: str
    started_at: datetime
    expires_at: datetime
    last_sync_at: datetime | None
    closed_at: datetime | None
    server_time: datetime
    catalog_snapshot: CatalogSnapshotResponse


class OfflineOrderItemRequest(BaseModel):
    client_item_id: UUID
    variant_id: UUID
    selected_option_ids: Annotated[list[UUID], Field(max_length=100)] = []
    quantity: Annotated[int, Field(ge=1, le=1_000_000)]
    note: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("selected_option_ids")
    @classmethod
    def unique_options(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("selected_option_ids must be unique")
        return value


class OfflinePaymentLineRequest(BaseModel):
    method: PaymentMethod
    amount_minor: str
    cash_received_minor: str | None = None
    reference: Annotated[str | None, Field(max_length=200)] = None
    external_settlement_confirmed: bool = False

    @field_validator("amount_minor", "cash_received_minor")
    @classmethod
    def minor_units(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isascii() or not value.isdigit() or len(value) > 19:
            raise ValueError("Money must be a non-negative minor-unit string")
        return value

class OfflinePaymentRequest(BaseModel):
    client_payment_id: UUID
    completed_at: datetime
    lines: Annotated[list[OfflinePaymentLineRequest], Field(max_length=100)]

    @field_validator("completed_at")
    @classmethod
    def aware_completed_at(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("completed_at must include a timezone")
        return value


class OfflineOrderRequest(BaseModel):
    client_order_id: UUID
    revision: Annotated[int, Field(ge=1)]
    base_server_version: Annotated[int | None, Field(ge=1)] = None
    catalog_snapshot_id: UUID
    offline_display_number: Annotated[int | None, Field(ge=1)] = None
    created_at: datetime
    updated_at: datetime
    order_type: OrderType
    status: Literal["OPEN", "CANCELLED", "PAID"]
    items: Annotated[list[OfflineOrderItemRequest], Field(max_length=500)]
    payment: OfflinePaymentRequest | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Offline timestamps must include a timezone")
        return value

    @field_validator("items")
    @classmethod
    def unique_items(cls, value: list[OfflineOrderItemRequest]) -> list[OfflineOrderItemRequest]:
        ids = [item.client_item_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("client_item_id must be unique within an order")
        return value

    def model_post_init(self, __context: object) -> None:
        if (self.status == "PAID") != (self.payment is not None):
            raise ValueError("PAID orders require payment and other statuses forbid it")


class OfflineSyncRequest(BaseModel):
    session_id: UUID
    orders: Annotated[list[OfflineOrderRequest], Field(max_length=100)]

    @field_validator("orders")
    @classmethod
    def unique_orders(cls, value: list[OfflineOrderRequest]) -> list[OfflineOrderRequest]:
        ids = [order.client_order_id for order in value]
        if len(ids) != len(set(ids)):
            raise ValueError("client_order_id must be unique within a batch")
        return value


class OfflineSyncResultResponse(BaseModel):
    client_order_id: UUID
    revision: int
    status: Literal["SYNCED", "CONFLICT"]
    code: str | None = None
    server_order_id: UUID | None = None
    server_order_number: int | None = None
    server_version: int | None = None
    payment_id: UUID | None = None


class OfflineSyncResponse(BaseModel):
    server_time: datetime
    results: list[OfflineSyncResultResponse]


class PingResponse(BaseModel):
    ok: Literal[True] = True
    server_time: datetime
