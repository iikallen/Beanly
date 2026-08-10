from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SupplierCreated:
    organization_id: UUID
    supplier_id: UUID


@dataclass(frozen=True, slots=True)
class PurchaseOrderCreated:
    organization_id: UUID
    purchase_order_id: UUID


@dataclass(frozen=True, slots=True)
class PurchaseOrderSubmitted:
    organization_id: UUID
    purchase_order_id: UUID


@dataclass(frozen=True, slots=True)
class GoodsReceiptCreated:
    organization_id: UUID
    goods_receipt_id: UUID


@dataclass(frozen=True, slots=True)
class GoodsReceiptPosted:
    organization_id: UUID
    goods_receipt_id: UUID
    inventory_transaction_id: UUID


@dataclass(frozen=True, slots=True)
class GoodsReceiptReversed:
    organization_id: UUID
    goods_receipt_id: UUID


@dataclass(frozen=True, slots=True)
class PurchaseOrderPartiallyReceived:
    organization_id: UUID
    purchase_order_id: UUID


@dataclass(frozen=True, slots=True)
class PurchaseOrderReceived:
    organization_id: UUID
    purchase_order_id: UUID


@dataclass(frozen=True, slots=True)
class SupplierReturnCreated:
    organization_id: UUID
    supplier_return_id: UUID


@dataclass(frozen=True, slots=True)
class SupplierReturnPosted:
    organization_id: UUID
    supplier_return_id: UUID
    inventory_transaction_id: UUID


@dataclass(frozen=True, slots=True)
class SupplierReturnReversed:
    organization_id: UUID
    supplier_return_id: UUID
