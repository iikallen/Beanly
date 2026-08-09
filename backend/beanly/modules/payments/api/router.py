from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from beanly.modules.organizations.domain.exceptions import (
    InvalidLocationAccess,
    OrganizationAccessDenied,
)
from beanly.modules.payments.api.dependencies import (
    PaymentAccessDep,
    PaymentCreateDep,
    PaymentReadDep,
    PaymentServiceDep,
)
from beanly.modules.payments.api.schemas import (
    PaymentCompleteRequest,
    PaymentMethodResponse,
    PaymentResponse,
    ShiftPaymentSummaryResponse,
)
from beanly.modules.payments.application.payment_service import (
    CompletePaymentInput,
    PaymentLineInput,
)
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.exceptions import (
    InvalidPayment,
    OrderAlreadyPaid,
    OrderNotPayable,
    OrderShiftClosed,
    PaymentAmountMismatch,
    PaymentConflict,
    PaymentIdempotencyConflict,
    PaymentNotFound,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/methods", response_model=list[PaymentMethodResponse])
async def list_methods(_: PaymentAccessDep) -> list[PaymentMethodResponse]:
    names = {PaymentMethod.CASH: "Cash", PaymentMethod.CARD: "Card", PaymentMethod.OTHER: "Other"}
    return [PaymentMethodResponse(code=method, name=names[method]) for method in PaymentMethod]


@router.post(
    "/orders/{order_id}/complete",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_payment(
    order_id: UUID,
    payload: PaymentCompleteRequest,
    context: PaymentCreateDep,
    service: PaymentServiceDep,
) -> PaymentResponse:
    try:
        value = await service.complete(
            context,
            order_id,
            CompletePaymentInput(
                payload.client_payment_id,
                tuple(
                    PaymentLineInput(
                        line.method,
                        line.amount_minor,
                        line.cash_received_minor,
                        line.reference,
                    )
                    for line in payload.lines
                ),
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return PaymentResponse.from_entity(value)


@router.get("/orders/{order_id}", response_model=PaymentResponse)
async def get_order_payment(
    order_id: UUID,
    context: PaymentReadDep,
    service: PaymentServiceDep,
) -> PaymentResponse:
    try:
        value = await service.get_by_order(context, order_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return PaymentResponse.from_entity(value)


@router.get(
    "/shifts/{shift_id}/summary", response_model=ShiftPaymentSummaryResponse
)
async def get_shift_summary(
    shift_id: UUID,
    context: PaymentReadDep,
    service: PaymentServiceDep,
) -> ShiftPaymentSummaryResponse:
    try:
        value = await service.shift_summary(context, shift_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ShiftPaymentSummaryResponse.from_entity(value)


@router.get("", response_model=list[PaymentResponse])
async def list_payments(
    context: PaymentReadDep,
    service: PaymentServiceDep,
    location_id: UUID | None = None,
    shift_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    method: Annotated[PaymentMethod | None, Query()] = None,
) -> list[PaymentResponse]:
    try:
        values = await service.list(
            context,
            location_id=location_id,
            shift_id=shift_id,
            date_from=date_from,
            date_to=date_to,
            method=method,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return [PaymentResponse.from_entity(value) for value in values]


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    context: PaymentReadDep,
    service: PaymentServiceDep,
) -> PaymentResponse:
    try:
        value = await service.get(context, payment_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return PaymentResponse.from_entity(value)


def _http_error(exc: Exception) -> HTTPException:
    detail = {
        "code": getattr(exc, "code", "PAYMENT_ERROR"),
        "message": str(exc) or "Payment operation failed",
    }
    if isinstance(exc, PaymentNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(
        exc,
        (OrganizationAccessDenied, InvalidLocationAccess),
    ):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail)
    if isinstance(exc, (InvalidPayment, PaymentAmountMismatch, ValueError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(
        exc,
        (
            PaymentConflict,
            PaymentIdempotencyConflict,
            OrderAlreadyPaid,
            OrderNotPayable,
            OrderShiftClosed,
            IntegrityError,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    raise exc
