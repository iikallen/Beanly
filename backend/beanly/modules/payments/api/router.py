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
    TerminalManageDep,
    TerminalPaymentServiceDep,
)
from beanly.modules.payments.api.schemas import (
    ExternalPaymentAttemptCreateRequest,
    ExternalPaymentAttemptResponse,
    PaymentCompleteRequest,
    PaymentMethodResponse,
    PaymentResponse,
    ShiftPaymentSummaryResponse,
    TerminalBindingCreateRequest,
    TerminalBindingPatchRequest,
    TerminalBindingResponse,
)
from beanly.modules.payments.application.payment_service import (
    CompletePaymentInput,
    PaymentLineInput,
)
from beanly.modules.payments.application.terminal_service import ExternalAttemptInput
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.exceptions import (
    ExternalPaymentAttemptNotFound,
    ExternalTerminalUnavailable,
    InvalidPayment,
    OrderAlreadyPaid,
    OrderNotPayable,
    OrderShiftClosed,
    PaymentAmountMismatch,
    PaymentConflict,
    PaymentIdempotencyConflict,
    PaymentNotFound,
    TerminalBindingNotFound,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/methods", response_model=list[PaymentMethodResponse])
async def list_methods(_: PaymentAccessDep) -> list[PaymentMethodResponse]:
    names = {PaymentMethod.CASH: "Cash", PaymentMethod.CARD: "Card", PaymentMethod.OTHER: "Other"}
    return [PaymentMethodResponse(code=method, name=names[method]) for method in PaymentMethod]


@router.get("/terminal-bindings", response_model=list[TerminalBindingResponse])
async def list_terminal_bindings(
    register_id: UUID,
    context: PaymentCreateDep,
    service: TerminalPaymentServiceDep,
) -> list[TerminalBindingResponse]:
    try:
        values = await service.list_bindings(context, register_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [TerminalBindingResponse.from_entity(value) for value in values]


@router.post(
    "/terminal-bindings",
    response_model=TerminalBindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_terminal_binding(
    payload: TerminalBindingCreateRequest,
    context: TerminalManageDep,
    service: TerminalPaymentServiceDep,
) -> TerminalBindingResponse:
    try:
        value = await service.create_binding(context, **payload.model_dump())
    except Exception as exc:
        raise _http_error(exc) from exc
    return TerminalBindingResponse.from_entity(value)


@router.patch("/terminal-bindings/{binding_id}", response_model=TerminalBindingResponse)
async def update_terminal_binding(
    binding_id: UUID,
    payload: TerminalBindingPatchRequest,
    context: TerminalManageDep,
    service: TerminalPaymentServiceDep,
) -> TerminalBindingResponse:
    try:
        value = await service.update_binding(
            context, binding_id, **payload.model_dump(exclude_unset=True)
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return TerminalBindingResponse.from_entity(value)


@router.post(
    "/external-attempts",
    response_model=ExternalPaymentAttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_external_attempt(
    payload: ExternalPaymentAttemptCreateRequest,
    context: PaymentCreateDep,
    service: TerminalPaymentServiceDep,
) -> ExternalPaymentAttemptResponse:
    try:
        value = await service.create_attempt(context, ExternalAttemptInput(**payload.model_dump()))
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExternalPaymentAttemptResponse.from_entity(value)


@router.get("/external-attempts/{attempt_id}", response_model=ExternalPaymentAttemptResponse)
async def get_external_attempt(
    attempt_id: UUID,
    context: PaymentCreateDep,
    service: TerminalPaymentServiceDep,
) -> ExternalPaymentAttemptResponse:
    try:
        value = await service.get_attempt(context, attempt_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExternalPaymentAttemptResponse.from_entity(value)


@router.post(
    "/external-attempts/{attempt_id}/start",
    response_model=ExternalPaymentAttemptResponse,
)
async def start_external_attempt(
    attempt_id: UUID,
    context: PaymentCreateDep,
    service: TerminalPaymentServiceDep,
) -> ExternalPaymentAttemptResponse:
    try:
        value = await service.start(context, attempt_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExternalPaymentAttemptResponse.from_entity(value)


@router.post(
    "/external-attempts/{attempt_id}/reconcile",
    response_model=ExternalPaymentAttemptResponse,
)
async def reconcile_external_attempt(
    attempt_id: UUID,
    context: PaymentCreateDep,
    service: TerminalPaymentServiceDep,
) -> ExternalPaymentAttemptResponse:
    try:
        value = await service.reconcile(context, attempt_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExternalPaymentAttemptResponse.from_entity(value)


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
    if isinstance(
        exc, (PaymentNotFound, ExternalPaymentAttemptNotFound, TerminalBindingNotFound)
    ):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, ExternalTerminalUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
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
