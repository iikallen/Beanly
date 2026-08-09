from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from beanly.modules.inventory.domain.exceptions import (
    DuplicateInventoryResource,
    IdempotencyConflict,
    InvalidInventoryOperation,
    InvalidInventoryUnit,
    InventoryNotFound,
)
from beanly.modules.purchasing.api.dependencies import (
    PurchasingCancelDep,
    PurchasingCreateDep,
    PurchasingReadDep,
    PurchasingReceiveDep,
    PurchasingServiceDep,
    PurchasingUpdateDep,
)
from beanly.modules.purchasing.api.schemas import (
    CreateOrderReceiptRequest,
    CreateOrderRequest,
    CreateReceiptRequest,
    OrderResponse,
    PostReceiptRequest,
    ReceiptLineRequest,
    ReceiptResponse,
    SupplierRequest,
    SupplierResponse,
    UpdateOrderRequest,
    UpdateReceiptRequest,
)
from beanly.modules.purchasing.application.commands import (
    CreateGoodsReceiptCommand,
    CreatePurchaseOrderCommand,
    PurchaseLineInput,
    ReceiptLineInput,
    SupplierInput,
    UpdateGoodsReceiptCommand,
    UpdatePurchaseOrderCommand,
)
from beanly.modules.purchasing.domain.enums import GoodsReceiptStatus, PurchaseOrderStatus
from beanly.modules.purchasing.domain.exceptions import (
    DuplicatePurchasingResource,
    InvalidPurchaseQuantity,
    InvalidPurchasingOperation,
    OverReceiptConfirmationRequired,
    PurchasingNotFound,
)

router = APIRouter(tags=["purchasing"])


@router.post("/suppliers", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierRequest,
    context: PurchasingCreateDep,
    service: PurchasingServiceDep,
) -> SupplierResponse:
    try:
        value = await service.create_supplier(context, _supplier_input(payload))
    except Exception as exc:
        raise _http_error(exc) from exc
    return SupplierResponse.model_validate(value)


@router.get("/suppliers", response_model=list[SupplierResponse])
async def list_suppliers(
    context: PurchasingReadDep,
    service: PurchasingServiceDep,
    include_inactive: bool = False,
) -> list[SupplierResponse]:
    return [
        SupplierResponse.model_validate(value)
        for value in await service.list_suppliers(context, include_inactive)
    ]


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID,
    context: PurchasingReadDep,
    service: PurchasingServiceDep,
) -> SupplierResponse:
    try:
        value = await service.get_supplier(context, supplier_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return SupplierResponse.model_validate(value)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierRequest,
    context: PurchasingUpdateDep,
    service: PurchasingServiceDep,
) -> SupplierResponse:
    try:
        value = await service.update_supplier(context, supplier_id, _supplier_input(payload))
    except Exception as exc:
        raise _http_error(exc) from exc
    return SupplierResponse.model_validate(value)


@router.post("/suppliers/{supplier_id}/deactivate", response_model=SupplierResponse)
async def deactivate_supplier(
    supplier_id: UUID,
    context: PurchasingUpdateDep,
    service: PurchasingServiceDep,
) -> SupplierResponse:
    try:
        value = await service.deactivate_supplier(context, supplier_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return SupplierResponse.model_validate(value)


@router.post(
    "/purchasing/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    payload: CreateOrderRequest,
    context: PurchasingCreateDep,
    service: PurchasingServiceDep,
) -> OrderResponse:
    try:
        detail = await service.create_order(
            context,
            CreatePurchaseOrderCommand(
                payload.supplier_id,
                payload.location_id,
                payload.warehouse_id,
                payload.expected_at,
                payload.note,
                tuple(_order_line(line) for line in payload.lines),
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_detail(detail)


@router.get("/purchasing/orders", response_model=list[OrderResponse])
async def list_orders(
    context: PurchasingReadDep,
    service: PurchasingServiceDep,
    supplier_id: UUID | None = None,
    location_id: UUID | None = None,
    warehouse_id: UUID | None = None,
    status_filter: Annotated[PurchaseOrderStatus | None, Query(alias="status")] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[OrderResponse]:
    try:
        rows = await service.list_orders(
            context,
            supplier_id,
            location_id,
            warehouse_id,
            status_filter,
            date_from,
            date_to,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return [OrderResponse.from_row(row) for row in rows]


@router.get("/purchasing/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    context: PurchasingReadDep,
    service: PurchasingServiceDep,
) -> OrderResponse:
    try:
        detail = await service.get_order(context, order_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_detail(detail)


@router.patch("/purchasing/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: UUID,
    payload: UpdateOrderRequest,
    context: PurchasingUpdateDep,
    service: PurchasingServiceDep,
) -> OrderResponse:
    fields = payload.model_fields_set
    try:
        detail = await service.update_order(
            context,
            order_id,
            UpdatePurchaseOrderCommand(
                payload.supplier_id,
                payload.location_id,
                payload.warehouse_id,
                payload.expected_at,
                "expected_at" in fields,
                payload.note,
                "note" in fields,
                (
                    tuple(_order_line(line) for line in payload.lines)
                    if payload.lines is not None
                    else None
                ),
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_detail(detail)


@router.post("/purchasing/orders/{order_id}/submit", response_model=OrderResponse)
async def submit_order(
    order_id: UUID,
    context: PurchasingUpdateDep,
    service: PurchasingServiceDep,
) -> OrderResponse:
    try:
        detail = await service.submit_order(context, order_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_detail(detail)


@router.post("/purchasing/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    context: PurchasingCancelDep,
    service: PurchasingServiceDep,
) -> OrderResponse:
    try:
        detail = await service.cancel_order(context, order_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_detail(detail)


@router.post(
    "/purchasing/orders/{order_id}/receipts",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_receipt(
    order_id: UUID,
    payload: CreateOrderReceiptRequest,
    context: PurchasingReceiveDep,
    service: PurchasingServiceDep,
) -> ReceiptResponse:
    try:
        detail = await service.create_order_receipt(
            context,
            order_id,
            tuple(_receipt_line(line) for line in payload.lines),
            payload.document_number,
            payload.received_at,
            payload.note,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ReceiptResponse.from_detail(detail)


@router.post(
    "/purchasing/receipts",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_receipt(
    payload: CreateReceiptRequest,
    context: PurchasingReceiveDep,
    service: PurchasingServiceDep,
) -> ReceiptResponse:
    try:
        detail = await service.create_receipt(
            context,
            CreateGoodsReceiptCommand(
                payload.supplier_id,
                payload.location_id,
                payload.warehouse_id,
                payload.purchase_order_id,
                payload.document_number,
                payload.received_at,
                payload.note,
                tuple(_receipt_line(line) for line in payload.lines),
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ReceiptResponse.from_detail(detail)


@router.get("/purchasing/receipts", response_model=list[ReceiptResponse])
async def list_receipts(
    context: PurchasingReadDep,
    service: PurchasingServiceDep,
    purchase_order_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status_filter: Annotated[GoodsReceiptStatus | None, Query(alias="status")] = None,
) -> list[ReceiptResponse]:
    try:
        rows = await service.list_receipts(context, purchase_order_id, supplier_id, status_filter)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [ReceiptResponse.from_row(row) for row in rows]


@router.get("/purchasing/receipts/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: UUID,
    context: PurchasingReadDep,
    service: PurchasingServiceDep,
) -> ReceiptResponse:
    try:
        detail = await service.get_receipt(context, receipt_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ReceiptResponse.from_detail(detail)


@router.patch("/purchasing/receipts/{receipt_id}", response_model=ReceiptResponse)
async def update_receipt(
    receipt_id: UUID,
    payload: UpdateReceiptRequest,
    context: PurchasingReceiveDep,
    service: PurchasingServiceDep,
) -> ReceiptResponse:
    fields = payload.model_fields_set
    try:
        detail = await service.update_receipt(
            context,
            receipt_id,
            UpdateGoodsReceiptCommand(
                payload.supplier_id,
                payload.location_id,
                payload.warehouse_id,
                payload.document_number,
                "document_number" in fields,
                payload.received_at,
                payload.note,
                "note" in fields,
                (
                    tuple(_receipt_line(line) for line in payload.lines)
                    if payload.lines is not None
                    else None
                ),
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ReceiptResponse.from_detail(detail)


@router.post("/purchasing/receipts/{receipt_id}/post", response_model=ReceiptResponse)
async def post_receipt(
    receipt_id: UUID,
    payload: PostReceiptRequest,
    context: PurchasingReceiveDep,
    service: PurchasingServiceDep,
) -> ReceiptResponse:
    try:
        detail = await service.post_receipt(context, receipt_id, payload.confirm_over_receipt)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ReceiptResponse.from_detail(detail)


@router.post("/purchasing/receipts/{receipt_id}/reverse", response_model=ReceiptResponse)
async def reverse_receipt(
    receipt_id: UUID,
    context: PurchasingReceiveDep,
    service: PurchasingServiceDep,
) -> ReceiptResponse:
    try:
        detail = await service.reverse_receipt(context, receipt_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ReceiptResponse.from_detail(detail)


def _supplier_input(payload: SupplierRequest) -> SupplierInput:
    return SupplierInput(**payload.model_dump())


def _order_line(line) -> PurchaseLineInput:
    return PurchaseLineInput(
        line.inventory_item_id,
        line.quantity,
        line.purchase_unit,
        line.unit_multiplier,
        line.unit_price,
    )


def _receipt_line(line: ReceiptLineRequest) -> ReceiptLineInput:
    return ReceiptLineInput(
        line.inventory_item_id,
        line.quantity,
        line.purchase_unit,
        line.unit_multiplier,
        line.unit_price,
        line.purchase_order_line_id,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (PurchasingNotFound, InventoryNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Purchasing resource not found")
    if isinstance(exc, OverReceiptConfirmationRequired):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": exc.code,
                "message": "Received quantity exceeds the purchase order",
            },
        )
    if isinstance(
        exc,
        (
            DuplicatePurchasingResource,
            InvalidPurchasingOperation,
            DuplicateInventoryResource,
            IdempotencyConflict,
            InvalidInventoryOperation,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc) or "Purchasing conflict")
    if isinstance(exc, (InvalidPurchaseQuantity, InvalidInventoryUnit, ValueError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    raise exc
