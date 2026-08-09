from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SupplierInput:
    name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = None
    address: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class PurchaseLineInput:
    inventory_item_id: UUID
    quantity: Decimal
    purchase_unit: str
    unit_multiplier: Decimal | None
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class CreatePurchaseOrderCommand:
    supplier_id: UUID
    location_id: UUID
    warehouse_id: UUID
    expected_at: datetime | None
    note: str | None
    lines: tuple[PurchaseLineInput, ...]


@dataclass(frozen=True, slots=True)
class UpdatePurchaseOrderCommand:
    supplier_id: UUID | None = None
    location_id: UUID | None = None
    warehouse_id: UUID | None = None
    expected_at: datetime | None = None
    expected_at_set: bool = False
    note: str | None = None
    note_set: bool = False
    lines: tuple[PurchaseLineInput, ...] | None = None


@dataclass(frozen=True, slots=True)
class ReceiptLineInput:
    inventory_item_id: UUID
    quantity: Decimal
    purchase_unit: str
    unit_multiplier: Decimal | None
    unit_price: Decimal
    purchase_order_line_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateGoodsReceiptCommand:
    supplier_id: UUID
    location_id: UUID
    warehouse_id: UUID
    purchase_order_id: UUID | None
    document_number: str | None
    received_at: datetime
    note: str | None
    lines: tuple[ReceiptLineInput, ...]


@dataclass(frozen=True, slots=True)
class UpdateGoodsReceiptCommand:
    supplier_id: UUID | None = None
    location_id: UUID | None = None
    warehouse_id: UUID | None = None
    document_number: str | None = None
    document_number_set: bool = False
    received_at: datetime | None = None
    note: str | None = None
    note_set: bool = False
    lines: tuple[ReceiptLineInput, ...] | None = None
