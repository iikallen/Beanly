from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from beanly.modules.organizations.domain.exceptions import (
    InvalidLocationAccess,
    OrganizationAccessDenied,
)
from beanly.modules.reservations.api.dependencies import (
    FohConfigureDep,
    FohManageDep,
    FohReadDep,
    ReservationServiceDep,
)
from beanly.modules.reservations.api.schemas import (
    DiningFloorResponse,
    DiningSectionCreate,
    DiningSectionPatch,
    DiningSectionResponse,
    DiningTableCreate,
    DiningTablePatch,
    DiningTableResponse,
    DiningVisitResponse,
    DirectVisitCreate,
    GuestReservationCreate,
    GuestReservationCreatedResponse,
    OpenCheckRequest,
    PublicReservationLocationResponse,
    PublicReservationResponse,
    ReservationAvailabilityResponse,
    ReservationResponse,
    ReservationSettingsResponse,
    ReservationSettingsWrite,
    SeatRequest,
    StaffActionRequest,
    StaffReservationCreate,
    WaitlistCreate,
    WaitlistResponse,
)
from beanly.modules.reservations.domain.enums import ReservationStatus
from beanly.modules.reservations.domain.exceptions import (
    InvalidGuestToken,
    ReservationConflict,
    ReservationError,
    ReservationNotFound,
)

public_router = APIRouter(prefix="/public/reservations", tags=["public-reservations"])
router = APIRouter(tags=["front-of-house"])


@public_router.get("/status/{token}", response_model=PublicReservationResponse)
async def public_status(token: str, service: ReservationServiceDep):
    try:
        return await service.public_status(token)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.post("/status/{token}/cancel", response_model=PublicReservationResponse)
async def public_cancel(token: str, service: ReservationServiceDep):
    try:
        return await service.public_cancel(token)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.get("/{slug}/availability", response_model=ReservationAvailabilityResponse)
async def availability(
    slug: str,
    requested_date: Annotated[date, Query(alias="date")],
    party_size: Annotated[int, Query(gt=0, le=1000)],
    service: ReservationServiceDep,
):
    try:
        return await service.availability(slug, requested_date, party_size)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.post(
    "/{slug}",
    response_model=GuestReservationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_guest(slug: str, payload: GuestReservationCreate, service: ReservationServiceDep):
    try:
        return await service.create_guest(slug, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.get("/{slug}", response_model=PublicReservationLocationResponse)
async def public_location(slug: str, service: ReservationServiceDep):
    try:
        return await service.public_location(slug)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/reservation-settings/{location_id}", response_model=ReservationSettingsResponse)
async def get_settings(location_id: UUID, context: FohConfigureDep, service: ReservationServiceDep):
    try:
        return await service.get_settings(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/reservation-settings", response_model=ReservationSettingsResponse)
async def save_settings(
    payload: ReservationSettingsWrite, context: FohConfigureDep, service: ReservationServiceDep
):
    try:
        return await service.save_settings(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/dining-sections", response_model=list[DiningSectionResponse])
async def list_sections(location_id: UUID, context: FohReadDep, service: ReservationServiceDep):
    try:
        return await service.list_sections(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/dining-sections",
    response_model=DiningSectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    payload: DiningSectionCreate, context: FohConfigureDep, service: ReservationServiceDep
):
    try:
        return await service.create_section(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/dining-sections/{section_id}", response_model=DiningSectionResponse)
async def patch_section(
    section_id: UUID,
    payload: DiningSectionPatch,
    context: FohConfigureDep,
    service: ReservationServiceDep,
):
    try:
        return await service.patch_section(context, section_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/dining-tables", response_model=list[DiningTableResponse])
async def list_tables(location_id: UUID, context: FohReadDep, service: ReservationServiceDep):
    try:
        return await service.list_tables(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/dining-tables",
    response_model=DiningTableResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_table(
    payload: DiningTableCreate, context: FohConfigureDep, service: ReservationServiceDep
):
    try:
        return await service.create_table(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/dining-tables/{table_id}", response_model=DiningTableResponse)
async def patch_table(
    table_id: UUID,
    payload: DiningTablePatch,
    context: FohConfigureDep,
    service: ReservationServiceDep,
):
    try:
        return await service.patch_table(context, table_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/reservations", response_model=list[ReservationResponse])
async def list_reservations(
    location_id: UUID,
    context: FohReadDep,
    service: ReservationServiceDep,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    reservation_status: Annotated[ReservationStatus | None, Query(alias="status")] = None,
):
    try:
        return await service.list_reservations(
            context, location_id, date_from, date_to, reservation_status
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/reservations", response_model=ReservationResponse, status_code=status.HTTP_201_CREATED
)
async def create_reservation(
    payload: StaffReservationCreate, context: FohManageDep, service: ReservationServiceDep
):
    try:
        return await service.create_staff_reservation(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/reservations/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(
    reservation_id: UUID, context: FohReadDep, service: ReservationServiceDep
):
    try:
        return await service.get_reservation(context, reservation_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: UUID,
    payload: StaffActionRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.cancel_reservation(
            context, reservation_id, payload.client_action_id, payload.reason
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/reservations/{reservation_id}/no-show", response_model=ReservationResponse)
async def no_show(
    reservation_id: UUID,
    payload: StaffActionRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.no_show(context, reservation_id, payload.client_action_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/reservations/{reservation_id}/seat", response_model=DiningVisitResponse)
async def seat_reservation(
    reservation_id: UUID,
    payload: SeatRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.seat_reservation(
            context, reservation_id, payload.client_action_id, payload.dining_table_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/waitlist", response_model=list[WaitlistResponse])
async def list_waitlist(location_id: UUID, context: FohReadDep, service: ReservationServiceDep):
    try:
        return await service.list_waitlist(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/waitlist", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
async def create_waitlist(
    payload: WaitlistCreate, context: FohManageDep, service: ReservationServiceDep
):
    try:
        return await service.create_waitlist(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/waitlist/{entry_id}/cancel", response_model=WaitlistResponse)
async def cancel_waitlist(
    entry_id: UUID,
    payload: StaffActionRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.cancel_waitlist(context, entry_id, payload.client_action_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/waitlist/{entry_id}/seat", response_model=DiningVisitResponse)
async def seat_waitlist(
    entry_id: UUID,
    payload: SeatRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.seat_waitlist(
            context, entry_id, payload.client_action_id, payload.dining_table_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/dining-floor", response_model=DiningFloorResponse)
async def floor(location_id: UUID, context: FohReadDep, service: ReservationServiceDep):
    try:
        return await service.floor(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/dining-visits", response_model=DiningVisitResponse, status_code=status.HTTP_201_CREATED
)
async def direct_visit(
    payload: DirectVisitCreate, context: FohManageDep, service: ReservationServiceDep
):
    try:
        return await service.direct_visit(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/dining-visits/{visit_id}", response_model=DiningVisitResponse)
async def get_visit(visit_id: UUID, context: FohReadDep, service: ReservationServiceDep):
    try:
        return await service.get_visit(context, visit_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/dining-visits/{visit_id}/open-check", response_model=DiningVisitResponse)
async def open_check(
    visit_id: UUID,
    payload: OpenCheckRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.open_check(context, visit_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/dining-visits/{visit_id}/close", response_model=DiningVisitResponse)
async def close_visit(
    visit_id: UUID,
    payload: StaffActionRequest,
    context: FohManageDep,
    service: ReservationServiceDep,
):
    try:
        return await service.close_visit(context, visit_id, payload.client_action_id)
    except Exception as exc:
        raise _http_error(exc) from exc


def _http_error(exc: Exception) -> HTTPException:
    detail = {"code": getattr(exc, "code", "RESERVATION_ERROR"), "message": str(exc)}
    if isinstance(exc, (ReservationNotFound, InvalidGuestToken)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, (OrganizationAccessDenied, InvalidLocationAccess)):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail)
    if isinstance(exc, (ReservationConflict, IntegrityError)):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    if isinstance(exc, (ReservationError, ValueError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    raise exc
