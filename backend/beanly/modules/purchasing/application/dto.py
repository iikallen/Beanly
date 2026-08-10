from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from beanly.modules.purchasing.domain.entities import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierReturn,
    SupplierReturnLine,
)


@dataclass(frozen=True, slots=True)
class PurchaseOrderDetail:
    order: PurchaseOrder
    lines: tuple[PurchaseOrderLine, ...]
    received_base_quantities: dict[UUID, Decimal]
    supplier_name: str


@dataclass(frozen=True, slots=True)
class GoodsReceiptDetail:
    receipt: GoodsReceipt
    lines: tuple[GoodsReceiptLine, ...]
    supplier_name: str
    purchase_order_number: str | None
    returned_base_quantities: dict[UUID, Decimal] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrderListRow:
    order: PurchaseOrder
    supplier_name: str
    total_minor: int


@dataclass(frozen=True, slots=True)
class ReceiptListRow:
    receipt: GoodsReceipt
    supplier_name: str
    total_minor: int


@dataclass(frozen=True, slots=True)
class SupplierReturnDetail:
    supplier_return: SupplierReturn
    lines: tuple[SupplierReturnLine, ...]
    supplier_name: str
    goods_receipt_number: str | None
    returned_base_quantities: dict[UUID, Decimal]


@dataclass(frozen=True, slots=True)
class SupplierReturnListRow:
    supplier_return: SupplierReturn
    supplier_name: str
    goods_receipt_number: str | None
    total_minor: int
