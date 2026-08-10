from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.purchasing.domain.enums import (
    GoodsReceiptStatus,
    PurchaseOrderStatus,
    SupplierReturnStatus,
)


@dataclass(frozen=True, slots=True)
class Supplier:
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


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    supplier_id: UUID
    number: str
    status: PurchaseOrderStatus
    currency_code: str
    ordered_at: datetime | None
    expected_at: datetime | None
    note: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PurchaseOrderLine:
    id: UUID
    purchase_order_id: UUID
    inventory_item_id: UUID
    ordered_quantity: Decimal
    base_quantity: Decimal
    purchase_unit: str
    unit_multiplier: Decimal
    unit_price: Decimal
    line_total_minor: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GoodsReceipt:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    purchase_order_id: UUID | None
    supplier_id: UUID
    number: str
    status: GoodsReceiptStatus
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


@dataclass(frozen=True, slots=True)
class GoodsReceiptLine:
    id: UUID
    goods_receipt_id: UUID
    purchase_order_line_id: UUID | None
    inventory_item_id: UUID
    received_quantity: Decimal
    base_quantity: Decimal
    purchase_unit: str
    unit_multiplier: Decimal
    unit_price: Decimal
    line_total_minor: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SupplierReturn:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    supplier_id: UUID
    goods_receipt_id: UUID | None
    number: str
    status: SupplierReturnStatus
    document_number: str | None
    returned_at: datetime
    note: str | None
    created_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    inventory_transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SupplierReturnLine:
    id: UUID
    supplier_return_id: UUID
    goods_receipt_line_id: UUID | None
    inventory_item_id: UUID
    return_quantity: Decimal
    base_quantity: Decimal
    purchase_unit: str
    unit_multiplier: Decimal
    unit_price: Decimal
    line_total_minor: int
    created_at: datetime
