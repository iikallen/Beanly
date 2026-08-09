from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from beanly.modules.inventory.domain.value_objects import decimal_string
from beanly.modules.purchasing.application.dto import (
    GoodsReceiptDetail,
    OrderListRow,
    PurchaseOrderDetail,
    ReceiptListRow,
)
from beanly.modules.purchasing.domain.enums import GoodsReceiptStatus, PurchaseOrderStatus


def _decimal_string(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError("Decimal values must be JSON strings")
    return value


class SupplierRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    contact_name: Annotated[str | None, Field(max_length=150)] = None
    phone: Annotated[str | None, Field(max_length=50)] = None
    email: Annotated[str | None, Field(max_length=255)] = None
    tax_id: Annotated[str | None, Field(max_length=100)] = None
    address: Annotated[str | None, Field(max_length=2000)] = None
    note: Annotated[str | None, Field(max_length=2000)] = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    tax_id: str | None
    address: str | None
    note: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PurchaseLineRequest(BaseModel):
    inventory_item_id: UUID
    quantity: Decimal
    purchase_unit: Annotated[
        str,
        Field(
            min_length=1,
            max_length=50,
            validation_alias=AliasChoices("purchase_unit", "unit"),
        ),
    ]
    unit_multiplier: Decimal | None = None
    unit_price: Decimal

    _quantity_string = field_validator("quantity", mode="before")(_decimal_string)
    _multiplier_string = field_validator("unit_multiplier", mode="before")(
        lambda value: None if value is None else _decimal_string(value)
    )
    _price_string = field_validator("unit_price", mode="before")(_decimal_string)


class CreateOrderRequest(BaseModel):
    supplier_id: UUID
    location_id: UUID
    warehouse_id: UUID
    expected_at: datetime | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None
    lines: Annotated[list[PurchaseLineRequest], Field(min_length=1, max_length=500)]


class UpdateOrderRequest(BaseModel):
    supplier_id: UUID | None = None
    location_id: UUID | None = None
    warehouse_id: UUID | None = None
    expected_at: datetime | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None
    lines: Annotated[list[PurchaseLineRequest] | None, Field(max_length=500)] = None


class OrderLineResponse(BaseModel):
    id: UUID
    purchase_order_id: UUID
    inventory_item_id: UUID
    ordered_quantity: str
    base_quantity: str
    purchase_unit: str
    unit_multiplier: str
    unit_price: str
    line_total_minor: str
    received_base_quantity: str
    remaining_base_quantity: str
    created_at: datetime
    updated_at: datetime


class OrderResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    supplier_id: UUID
    supplier_name: str
    number: str
    status: PurchaseOrderStatus
    currency_code: str
    total_minor: str
    ordered_at: datetime | None
    expected_at: datetime | None
    note: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    lines: list[OrderLineResponse] = Field(default_factory=list)

    @classmethod
    def from_detail(cls, detail: PurchaseOrderDetail) -> "OrderResponse":
        order = detail.order
        lines = []
        for line in detail.lines:
            received = detail.received_base_quantities.get(line.id, Decimal(0))
            lines.append(
                OrderLineResponse(
                    id=line.id,
                    purchase_order_id=line.purchase_order_id,
                    inventory_item_id=line.inventory_item_id,
                    ordered_quantity=decimal_string(line.ordered_quantity),
                    base_quantity=decimal_string(line.base_quantity),
                    purchase_unit=line.purchase_unit,
                    unit_multiplier=decimal_string(line.unit_multiplier),
                    unit_price=decimal_string(line.unit_price),
                    line_total_minor=str(line.line_total_minor),
                    received_base_quantity=decimal_string(received),
                    remaining_base_quantity=decimal_string(line.base_quantity - received),
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
            )
        return cls(
            **asdict(order),
            supplier_name=detail.supplier_name,
            total_minor=str(sum(line.line_total_minor for line in detail.lines)),
            lines=lines,
        )

    @classmethod
    def from_row(cls, row: OrderListRow) -> "OrderResponse":
        return cls(
            **asdict(row.order),
            supplier_name=row.supplier_name,
            total_minor=str(row.total_minor),
        )


class ReceiptLineRequest(BaseModel):
    purchase_order_line_id: UUID | None = None
    inventory_item_id: UUID
    quantity: Decimal
    purchase_unit: Annotated[
        str,
        Field(
            min_length=1,
            max_length=50,
            validation_alias=AliasChoices("purchase_unit", "unit"),
        ),
    ]
    unit_multiplier: Decimal | None = None
    unit_price: Decimal

    _quantity_string = field_validator("quantity", mode="before")(_decimal_string)
    _multiplier_string = field_validator("unit_multiplier", mode="before")(
        lambda value: None if value is None else _decimal_string(value)
    )
    _price_string = field_validator("unit_price", mode="before")(_decimal_string)


class CreateReceiptRequest(BaseModel):
    supplier_id: UUID
    location_id: UUID
    warehouse_id: UUID
    purchase_order_id: UUID | None = None
    document_number: Annotated[str | None, Field(max_length=100)] = None
    received_at: datetime
    note: Annotated[str | None, Field(max_length=2000)] = None
    lines: Annotated[list[ReceiptLineRequest], Field(min_length=1, max_length=500)]


class CreateOrderReceiptRequest(BaseModel):
    document_number: Annotated[str | None, Field(max_length=100)] = None
    received_at: datetime
    note: Annotated[str | None, Field(max_length=2000)] = None
    lines: Annotated[list[ReceiptLineRequest], Field(min_length=1, max_length=500)]


class UpdateReceiptRequest(BaseModel):
    supplier_id: UUID | None = None
    location_id: UUID | None = None
    warehouse_id: UUID | None = None
    document_number: Annotated[str | None, Field(max_length=100)] = None
    received_at: datetime | None = None
    note: Annotated[str | None, Field(max_length=2000)] = None
    lines: Annotated[list[ReceiptLineRequest] | None, Field(max_length=500)] = None


class PostReceiptRequest(BaseModel):
    confirm_over_receipt: bool = False


class ReceiptLineResponse(BaseModel):
    id: UUID
    goods_receipt_id: UUID
    purchase_order_line_id: UUID | None
    inventory_item_id: UUID
    received_quantity: str
    base_quantity: str
    purchase_unit: str
    unit_multiplier: str
    unit_price: str
    line_total_minor: str
    created_at: datetime


class ReceiptResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    purchase_order_id: UUID | None
    purchase_order_number: str | None
    supplier_id: UUID
    supplier_name: str
    number: str
    status: GoodsReceiptStatus
    total_minor: str
    document_number: str | None
    received_at: datetime
    note: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    inventory_transaction_id: UUID | None
    lines: list[ReceiptLineResponse] = Field(default_factory=list)

    @classmethod
    def from_detail(cls, detail: GoodsReceiptDetail) -> "ReceiptResponse":
        receipt = detail.receipt
        return cls(
            **asdict(receipt),
            supplier_name=detail.supplier_name,
            purchase_order_number=detail.purchase_order_number,
            total_minor=str(sum(line.line_total_minor for line in detail.lines)),
            lines=[
                ReceiptLineResponse(
                    id=line.id,
                    goods_receipt_id=line.goods_receipt_id,
                    purchase_order_line_id=line.purchase_order_line_id,
                    inventory_item_id=line.inventory_item_id,
                    received_quantity=decimal_string(line.received_quantity),
                    base_quantity=decimal_string(line.base_quantity),
                    purchase_unit=line.purchase_unit,
                    unit_multiplier=decimal_string(line.unit_multiplier),
                    unit_price=decimal_string(line.unit_price),
                    line_total_minor=str(line.line_total_minor),
                    created_at=line.created_at,
                )
                for line in detail.lines
            ],
        )

    @classmethod
    def from_row(cls, row: ReceiptListRow) -> "ReceiptResponse":
        return cls(
            **asdict(row.receipt),
            supplier_name=row.supplier_name,
            purchase_order_number=None,
            total_minor=str(row.total_minor),
        )


def supplier_input(payload: SupplierRequest) -> dict[str, object]:
    return payload.model_dump()
