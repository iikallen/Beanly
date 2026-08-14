from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from beanly.modules.refunds.api.dependencies import RefundReadDep, RefundServiceDep, RefundWriteDep
from beanly.modules.refunds.api.schemas import (
    RefundCreateRequest,
    RefundPreviewRequest,
    RefundPreviewResponse,
    RefundResponse,
)
from beanly.modules.refunds.application.dto import (
    RefundInput,
    RefundLineInput,
    RefundPaymentLineInput,
)
from beanly.modules.refunds.domain.enums import RefundStatus
from beanly.modules.refunds.domain.exceptions import (
    ExternalRefundNotConfirmed,
    InvalidRefund,
    OrderNotRefundable,
    RefundError,
    RefundIdempotencyConflict,
    RefundNotFound,
    RefundPaymentAmountExceeded,
    RefundQuantityExceeded,
    RefundTotalMismatch,
)

router = APIRouter(prefix="/refunds", tags=["refunds"])
payments_refunds_router = APIRouter(prefix="/payments", tags=["refunds"])


@router.post("/preview", response_model=RefundPreviewResponse)
async def preview(
    payload: RefundPreviewRequest, context: RefundWriteDep, service: RefundServiceDep
) -> RefundPreviewResponse:
    try:
        return RefundPreviewResponse.model_validate(await service.preview(context, _input(payload)))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
async def complete(
    payload: RefundCreateRequest, context: RefundWriteDep, service: RefundServiceDep
) -> RefundResponse:
    try:
        value = await service.complete(context, _input(payload))
        fiscal = await service.fiscal_status(context, value.id)
        return RefundResponse.from_entity(value, fiscal=fiscal)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("", response_model=list[RefundResponse])
async def list_refunds(
    context: RefundReadDep,
    service: RefundServiceDep,
    location_id: UUID | None = None,
    order_id: UUID | None = None,
    payment_id: UUID | None = None,
    status_: Annotated[RefundStatus | None, Query(alias="status")] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[RefundResponse]:
    if any(value is not None and value.utcoffset() is None for value in (date_from, date_to)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Dates must include timezone")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "date_from cannot exceed date_to"
        )
    values = await service.list_refunds(
        context,
        location_id=location_id,
        order_id=order_id,
        payment_id=payment_id,
        status=status_,
        date_from=date_from,
        date_to=date_to,
    )
    return [
        RefundResponse.from_entity(value, fiscal=await service.fiscal_status(context, value.id))
        for value in values
    ]


@router.get("/{refund_id}", response_model=RefundResponse)
async def get_refund(
    refund_id: UUID, context: RefundReadDep, service: RefundServiceDep
) -> RefundResponse:
    try:
        value = await service.get(context, refund_id)
        return RefundResponse.from_entity(
            value, fiscal=await service.fiscal_status(context, value.id)
        )
    except Exception as exc:
        raise _http_error(exc) from exc


def _input(payload: RefundPreviewRequest) -> RefundInput:
    return RefundInput(
        payload.payment_id,
        payload.reason,
        payload.note,
        tuple(
            RefundLineInput(line.order_item_id, line.quantity, line.restock_quantity)
            for line in payload.lines
        ),
        tuple(
            RefundPaymentLineInput(
                line.original_payment_line_id,
                line.amount_minor,
                line.external_refund_confirmed,
                line.reference,
            )
            for line in payload.payment_lines
        ),
        getattr(payload, "client_refund_id", None),
    )


def _http_error(exc: Exception) -> HTTPException:
    detail = {
        "code": exc.code if isinstance(exc, RefundError) else RefundError.code,
        "message": str(exc) or "Refund failed",
    }
    if isinstance(exc, RefundNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, (InvalidRefund, RefundTotalMismatch, ValueError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(
        exc,
        (
            RefundIdempotencyConflict,
            RefundQuantityExceeded,
            RefundPaymentAmountExceeded,
            OrderNotRefundable,
            ExternalRefundNotConfirmed,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    if isinstance(exc, RefundError):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    raise exc


@payments_refunds_router.get("/{payment_id}/refunds", response_model=list[RefundResponse])
async def payment_refunds(
    payment_id: UUID, context: RefundReadDep, service: RefundServiceDep
) -> list[RefundResponse]:
    values = await service.by_payment(context, payment_id)
    return [
        RefundResponse.from_entity(value, fiscal=await service.fiscal_status(context, value.id))
        for value in values
    ]
