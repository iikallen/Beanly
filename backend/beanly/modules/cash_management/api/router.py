from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from beanly.modules.cash_management.api.dependencies import (
    CashAdjustDep,
    CashApproveDep,
    CashCloseDep,
    CashReportDep,
    CashServiceDep,
    CashUseDep,
)
from beanly.modules.cash_management.api.schemas import (
    CashCloseRequest,
    CashDrawerDetailResponse,
    CashDrawerReportRow,
    CashDrawerResponse,
    CashDrawerSummaryResponse,
    CashMovementRequest,
    CashMovementResponse,
    FiscalShiftStatusResponse,
    VarianceApprovalRequest,
)
from beanly.modules.cash_management.domain.enums import CashMovementKind
from beanly.modules.cash_management.domain.exceptions import (
    CashCloseIdempotencyConflict,
    CashDrawerAlreadyClosed,
    CashDrawerNotFound,
    CashDrawerNotOpen,
    CashManagementError,
    CashMovementIdempotencyConflict,
    CashMovementInvalid,
    CashVarianceApprovalRequired,
    FiscalShiftCloseFailed,
    FiscalShiftCloseUnknown,
    FiscalShiftReconciliationRequired,
    ShiftCloseSyncPending,
)
from beanly.modules.organizations.domain.exceptions import (
    InvalidLocationAccess,
    OrganizationAccessDenied,
)
from beanly.modules.organizations.domain.permissions import Permission

router = APIRouter(prefix="/cash", tags=["cash-management"])
fiscal_shift_router = APIRouter(prefix="/fiscal/shifts", tags=["fiscal-shifts"])


@router.get("/drawers/current", response_model=CashDrawerResponse | None)
async def current_drawer(register_id: UUID, context: CashUseDep, service: CashServiceDep):
    try:
        value = await service.current(context, register_id)
        return (
            CashDrawerResponse.from_model(
                value, expected_visible=Permission.CASH_DRAWER_VIEW_EXPECTED in context.permissions
            )
            if value
            else None
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/drawers/{drawer_id}", response_model=CashDrawerResponse)
async def get_drawer(drawer_id: UUID, context: CashUseDep, service: CashServiceDep):
    try:
        return CashDrawerResponse.from_model(
            await service.get(context, drawer_id),
            expected_visible=Permission.CASH_DRAWER_VIEW_EXPECTED in context.permissions,
        )
    except Exception as exc:
        raise _http(exc) from exc


async def _movement(drawer_id, payload, context, service, kind):
    try:
        value = await service.movement(
            context,
            drawer_id,
            kind,
            payload.client_movement_id,
            int(payload.amount_minor),
            payload.reason,
            payload.note,
        )
        return CashMovementResponse.from_model(value)
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/drawers/{drawer_id}/pay-in", response_model=CashMovementResponse)
async def pay_in(
    drawer_id: UUID, payload: CashMovementRequest, context: CashAdjustDep, service: CashServiceDep
):
    return await _movement(drawer_id, payload, context, service, CashMovementKind.PAY_IN)


@router.post("/drawers/{drawer_id}/pay-out", response_model=CashMovementResponse)
async def pay_out(
    drawer_id: UUID, payload: CashMovementRequest, context: CashAdjustDep, service: CashServiceDep
):
    return await _movement(drawer_id, payload, context, service, CashMovementKind.PAY_OUT)


@router.get("/drawers/{drawer_id}/summary", response_model=CashDrawerSummaryResponse)
async def drawer_summary(drawer_id: UUID, context: CashUseDep, service: CashServiceDep):
    try:
        value = await service.summary(context, drawer_id)
        return CashDrawerSummaryResponse.from_result(
            value, expected_visible=Permission.CASH_DRAWER_VIEW_EXPECTED in context.permissions
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/drawers/{drawer_id}/close", response_model=CashDrawerSummaryResponse)
async def close_drawer(
    drawer_id: UUID, payload: CashCloseRequest, context: CashCloseDep, service: CashServiceDep
):
    try:
        value = await service.close(
            context,
            drawer_id,
            payload.client_close_id,
            int(payload.actual_cash_minor),
            payload.note,
            payload.pending_offline_operations,
        )
        return CashDrawerSummaryResponse.from_result(
            value, expected_visible=Permission.CASH_DRAWER_VIEW_EXPECTED in context.permissions
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/drawers/{drawer_id}/approve-variance", response_model=CashDrawerSummaryResponse)
async def approve_variance(
    drawer_id: UUID,
    payload: VarianceApprovalRequest,
    context: CashApproveDep,
    service: CashServiceDep,
):
    try:
        value = await service.approve_variance(context, drawer_id, payload.reason)
        return CashDrawerSummaryResponse.from_result(value, expected_visible=True)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/reports/drawers", response_model=list[CashDrawerReportRow])
async def list_drawer_reports(
    context: CashReportDep,
    service: CashServiceDep,
    location_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
):
    try:
        return [
            CashDrawerReportRow.model_validate(row)
            for row in await service.reports(
                context,
                location_id=location_id,
                date_from=date_from,
                date_to=date_to,
                status=status_filter,
            )
        ]
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/reports/drawers/{drawer_id}", response_model=CashDrawerDetailResponse)
async def drawer_report(drawer_id: UUID, context: CashReportDep, service: CashServiceDep):
    try:
        value = await service.detail(context, drawer_id)
        return CashDrawerDetailResponse(
            summary=CashDrawerSummaryResponse.from_result(value["summary"], expected_visible=True),
            movements=[CashMovementResponse.from_model(row) for row in value["movements"]],
        )
    except Exception as exc:
        raise _http(exc) from exc


@fiscal_shift_router.post("/{shift_id}/x-report", response_model=FiscalShiftStatusResponse)
async def x_report(shift_id: UUID, context: CashReportDep, service: CashServiceDep):
    try:
        return FiscalShiftStatusResponse.model_validate(await service.x_report(context, shift_id))
    except Exception as exc:
        raise _http(exc) from exc


@fiscal_shift_router.get("/{shift_id}/status", response_model=FiscalShiftStatusResponse)
async def fiscal_status(shift_id: UUID, context: CashUseDep, service: CashServiceDep):
    try:
        return FiscalShiftStatusResponse.model_validate(
            await service.fiscal_status(context, shift_id)
        )
    except Exception as exc:
        raise _http(exc) from exc


@fiscal_shift_router.post("/{shift_id}/reconcile", response_model=FiscalShiftStatusResponse)
async def reconcile_fiscal_shift(shift_id: UUID, context: CashApproveDep, service: CashServiceDep):
    try:
        return FiscalShiftStatusResponse.model_validate(
            await service.reconcile_fiscal(context, shift_id)
        )
    except Exception as exc:
        raise _http(exc) from exc


def _http(exc: Exception) -> HTTPException:
    detail = {
        "code": getattr(exc, "code", "CASH_MANAGEMENT_ERROR"),
        "message": str(exc) or "Cash operation failed",
    }
    if isinstance(exc, (InvalidLocationAccess, OrganizationAccessDenied)):
        detail = {"code": "CASH_DRAWER_NOT_FOUND", "message": "Cash drawer not found"}
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, CashDrawerNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, (CashMovementInvalid, ValueError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(
        exc,
        (
            CashDrawerNotOpen,
            CashDrawerAlreadyClosed,
            CashMovementIdempotencyConflict,
            CashCloseIdempotencyConflict,
            CashVarianceApprovalRequired,
            ShiftCloseSyncPending,
            FiscalShiftCloseFailed,
            FiscalShiftCloseUnknown,
            FiscalShiftReconciliationRequired,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    if isinstance(exc, CashManagementError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail)
    raise exc
