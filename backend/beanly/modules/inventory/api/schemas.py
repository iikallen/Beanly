from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from beanly.modules.inventory.domain.entities import TransactionDetail
from beanly.modules.inventory.domain.enums import (
    InventoryCountStatus,
    InventoryCountType,
    InventoryTransactionStatus,
    InventoryTransactionType,
    InventoryTransferStatus,
    WriteOffStatus,
)
from beanly.modules.inventory.domain.value_objects import UnitCode, decimal_string

Name = Annotated[str, Field(min_length=1, max_length=150)]


class CreateWarehouseRequest(BaseModel):
    location_id: UUID
    name: Name


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateItemRequest(BaseModel):
    name: Name
    sku: Annotated[str | None, Field(max_length=100)] = None
    base_unit: UnitCode

    @field_validator("base_unit")
    @classmethod
    def base_units_only(cls, value: UnitCode) -> UnitCode:
        if value not in {UnitCode.G, UnitCode.ML, UnitCode.PCS}:
            raise ValueError("base_unit must be g, ml or pcs")
        return value


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    sku: str | None
    base_unit: UnitCode
    is_active: bool
    created_at: datetime
    updated_at: datetime


class QuantityRequest(BaseModel):
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    unit_cost_amount: Decimal | None = None

    @field_validator("quantity", mode="before")
    @classmethod
    def quantity_must_be_a_decimal_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("quantity must be a decimal string")
        return value

    @field_validator("unit_cost_amount", mode="before")
    @classmethod
    def cost_must_be_a_decimal_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("unit_cost_amount must be a decimal string")
        return value


class AdjustmentRequest(BaseModel):
    warehouse_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    lines: Annotated[list[QuantityRequest], Field(min_length=1, max_length=500)]

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not (stripped := value.strip()):
            raise ValueError("reason must not be blank")
        return stripped


class OpeningBalanceRequest(BaseModel):
    warehouse_id: UUID
    items: Annotated[list[QuantityRequest], Field(min_length=1, max_length=500)]


class StockRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    warehouse_id: UUID
    inventory_item_id: UUID
    item_name: str
    sku: str | None
    quantity: Decimal
    base_unit: UnitCode
    average_unit_cost: Decimal | None
    inventory_value: Decimal | None
    updated_at: datetime | None

    @field_serializer("quantity", "average_unit_cost", "inventory_value")
    def serialize_quantity(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None


class InventoryValuationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency_code: str
    total_inventory_value: Decimal
    items: list[StockRowResponse]

    @field_serializer("total_inventory_value")
    def serialize_total(self, value: Decimal) -> str:
        return decimal_string(value)


class TransactionLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_id: UUID
    inventory_item_id: UUID
    quantity_delta: Decimal
    unit_cost_amount: Decimal | None
    total_cost_amount: Decimal | None
    quantity_after: Decimal | None
    average_unit_cost_after: Decimal | None
    created_at: datetime

    @field_serializer(
        "quantity_delta",
        "unit_cost_amount",
        "total_cost_amount",
        "quantity_after",
        "average_unit_cost_after",
    )
    def serialize_decimals(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None


class TransactionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    type: InventoryTransactionType
    status: InventoryTransactionStatus
    reference_type: str | None
    reference_id: UUID | None
    idempotency_key: str | None
    note: str | None
    created_by: UUID
    created_at: datetime
    posted_at: datetime | None
    reversal_of_id: UUID | None


class TransactionDetailResponse(TransactionSummaryResponse):
    lines: list[TransactionLineResponse]

    @classmethod
    def from_detail(cls, detail: TransactionDetail) -> "TransactionDetailResponse":
        return cls(
            **TransactionSummaryResponse.model_validate(detail.transaction).model_dump(),
            lines=[TransactionLineResponse.model_validate(line) for line in detail.lines],
        )


class MovementRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    type: InventoryTransactionType
    status: InventoryTransactionStatus
    quantity_delta: Decimal
    unit_cost_amount: Decimal | None
    total_cost_amount: Decimal | None
    quantity_after: Decimal | None
    average_unit_cost_after: Decimal | None
    reference_type: str | None
    reference_id: UUID | None
    note: str | None
    posted_at: datetime | None
    created_at: datetime

    @field_serializer(
        "quantity_delta",
        "unit_cost_amount",
        "total_cost_amount",
        "quantity_after",
        "average_unit_cost_after",
    )
    def serialize_decimals(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None


class WriteOffReasonRequest(BaseModel):
    name: Name


class WriteOffReasonPatch(BaseModel):
    name: Name | None = None
    is_active: bool | None = None


class WriteOffReasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OperationLineRequest(BaseModel):
    inventory_item_id: UUID
    quantity: Decimal
    unit: UnitCode
    note: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("quantity", mode="before")
    @classmethod
    def quantity_is_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("quantity must be a decimal string")
        return value


class WriteOffRequest(BaseModel):
    warehouse_id: UUID
    reason_id: UUID
    occurred_at: datetime
    note: Annotated[str | None, Field(max_length=1000)] = None
    lines: Annotated[list[OperationLineRequest], Field(min_length=1, max_length=500)]


class WriteOffLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    base_quantity: Decimal
    note: str | None

    @field_serializer("quantity", "base_quantity")
    def serialize_decimals(self, value: Decimal) -> str:
        return decimal_string(value)


class WriteOffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    number: str
    reason_id: UUID
    status: WriteOffStatus
    occurred_at: datetime
    note: str | None
    created_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    inventory_transaction_id: UUID | None
    total_cost_amount: Decimal | None
    created_at: datetime
    updated_at: datetime
    lines: list[WriteOffLineResponse]

    @field_serializer("total_cost_amount")
    def serialize_total(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None


class InventoryCountRequest(BaseModel):
    warehouse_id: UUID
    type: InventoryCountType
    inventory_item_ids: Annotated[list[UUID], Field(max_length=500)] = Field(
        default_factory=list
    )
    note: Annotated[str | None, Field(max_length=1000)] = None


class InventoryCountLineUpdate(BaseModel):
    inventory_item_id: UUID
    counted_quantity: Decimal
    unit: UnitCode
    unit_cost_amount: Decimal | None = None

    @field_validator("counted_quantity", "unit_cost_amount", mode="before")
    @classmethod
    def decimals_are_strings(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("quantities and costs must be decimal strings")
        return value


class InventoryCountLinesRequest(BaseModel):
    lines: Annotated[list[InventoryCountLineUpdate], Field(min_length=1, max_length=500)]


class InventoryCountPostRequest(BaseModel):
    confirm_stock_changes: bool = False


class InventoryCountLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inventory_item_id: UUID
    expected_quantity: Decimal
    counted_quantity: Decimal | None
    current_quantity_before_post: Decimal | None
    difference_quantity: Decimal | None
    difference_cost_amount: Decimal | None
    unit_cost_amount: Decimal | None

    @field_serializer(
        "expected_quantity",
        "counted_quantity",
        "current_quantity_before_post",
        "difference_quantity",
        "difference_cost_amount",
        "unit_cost_amount",
    )
    def serialize_decimals(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None


class InventoryCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    number: str
    type: InventoryCountType
    status: InventoryCountStatus
    snapshot_at: datetime
    started_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    cancelled_by: UUID | None
    cancelled_at: datetime | None
    inventory_transaction_id: UUID | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[InventoryCountLineResponse]


class InventoryTransferRequest(BaseModel):
    source_warehouse_id: UUID
    destination_warehouse_id: UUID
    occurred_at: datetime
    note: Annotated[str | None, Field(max_length=1000)] = None
    lines: Annotated[list[OperationLineRequest], Field(min_length=1, max_length=500)]


class InventoryTransferLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    base_quantity: Decimal

    @field_serializer("quantity", "base_quantity")
    def serialize_decimals(self, value: Decimal) -> str:
        return decimal_string(value)


class InventoryTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    number: str
    source_location_id: UUID
    source_warehouse_id: UUID
    destination_location_id: UUID
    destination_warehouse_id: UUID
    status: InventoryTransferStatus
    occurred_at: datetime
    note: str | None
    created_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    out_transaction_id: UUID | None
    in_transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime
    lines: list[InventoryTransferLineResponse]


class GlobalMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    warehouse_id: UUID
    location_id: UUID
    inventory_item_id: UUID
    item_name: str
    type: InventoryTransactionType
    quantity_delta: Decimal
    unit_code: UnitCode
    unit_cost_amount: Decimal | None
    total_cost_amount: Decimal | None
    reference_type: str | None
    reference_id: UUID | None
    note: str | None
    posted_at: datetime

    @field_serializer("quantity_delta", "unit_cost_amount", "total_cost_amount")
    def serialize_decimals(self, value: Decimal | None) -> str | None:
        return decimal_string(value) if value is not None else None
