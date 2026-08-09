from beanly.modules.purchasing.domain.entities import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from beanly.modules.purchasing.domain.enums import GoodsReceiptStatus, PurchaseOrderStatus
from beanly.modules.purchasing.infrastructure.db.models import (
    GoodsReceiptLineModel,
    GoodsReceiptModel,
    PurchaseOrderLineModel,
    PurchaseOrderModel,
    SupplierModel,
)


def to_supplier(value: SupplierModel) -> Supplier:
    return Supplier(
        value.id,
        value.organization_id,
        value.name,
        value.contact_name,
        value.phone,
        value.email,
        value.tax_id,
        value.address,
        value.note,
        value.is_active,
        value.created_at,
        value.updated_at,
    )


def to_order(value: PurchaseOrderModel) -> PurchaseOrder:
    return PurchaseOrder(
        value.id,
        value.organization_id,
        value.location_id,
        value.warehouse_id,
        value.supplier_id,
        value.number,
        PurchaseOrderStatus(value.status),
        value.currency_code,
        value.ordered_at,
        value.expected_at,
        value.note,
        value.created_by,
        value.created_at,
        value.updated_at,
    )


def to_order_line(value: PurchaseOrderLineModel) -> PurchaseOrderLine:
    return PurchaseOrderLine(
        value.id,
        value.purchase_order_id,
        value.inventory_item_id,
        value.ordered_quantity,
        value.base_quantity,
        value.purchase_unit,
        value.unit_multiplier,
        value.unit_price,
        value.line_total_minor,
        value.created_at,
        value.updated_at,
    )


def to_receipt(value: GoodsReceiptModel) -> GoodsReceipt:
    return GoodsReceipt(
        value.id,
        value.organization_id,
        value.location_id,
        value.warehouse_id,
        value.purchase_order_id,
        value.supplier_id,
        value.number,
        GoodsReceiptStatus(value.status),
        value.document_number,
        value.received_at,
        value.note,
        value.created_by,
        value.created_at,
        value.updated_at,
        value.posted_by,
        value.posted_at,
        value.reversed_by,
        value.reversed_at,
        value.inventory_transaction_id,
    )


def to_receipt_line(value: GoodsReceiptLineModel) -> GoodsReceiptLine:
    return GoodsReceiptLine(
        value.id,
        value.goods_receipt_id,
        value.purchase_order_line_id,
        value.inventory_item_id,
        value.received_quantity,
        value.base_quantity,
        value.purchase_unit,
        value.unit_multiplier,
        value.unit_price,
        value.line_total_minor,
        value.created_at,
    )
