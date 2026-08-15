from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from beanly.modules.online_ordering.api.dependencies import (
    OnlineOrderingManageDep,
    OnlineOrderingServiceDep,
    OnlineOrdersManageDep,
    OnlineOrdersReadDep,
)
from beanly.modules.online_ordering.api.schemas import (
    AvailabilityResponse,
    ChannelReportRow,
    DeliveryZonePatch,
    DeliveryZoneResponse,
    DeliveryZoneWrite,
    FulfillmentOptionsResponse,
    LocationSettingsResponse,
    LocationSettingsWrite,
    OnlineOrderResponse,
    PauseRequest,
    PublicMenuResponse,
    PublicOrderCreatedResponse,
    PublicOrderingResponse,
    PublicOrderStatusResponse,
    QuoteRequest,
    QuoteResponse,
    ReadinessResponse,
    ResumeRequest,
    StaffActionRequest,
    StationCreate,
    StationPatch,
    StationResponse,
    SubmitOrderRequest,
)
from beanly.modules.online_ordering.domain.enums import OnlineOrderStatus
from beanly.modules.online_ordering.domain.exceptions import (
    OnlineFulfillmentSlotUnavailable,
    OnlineFulfillmentUnavailable,
    OnlineOrderAlreadyAccepted,
    OnlineOrderCancellationForbidden,
    OnlineOrderIdempotencyConflict,
    OnlineOrderingError,
    OnlineOrderingNotFound,
    OnlineOrderingUnavailable,
    OnlineOrderInvalidStation,
    OnlineOrderQuoteChanged,
)

public_router = APIRouter(prefix="/public/ordering", tags=["public-online-ordering"])
router = APIRouter(tags=["online-ordering"])


@public_router.get("/orders/{status_token}", response_model=PublicOrderStatusResponse)
async def public_status(
    status_token: str, service: OnlineOrderingServiceDep
) -> PublicOrderStatusResponse:
    try:
        return PublicOrderStatusResponse.from_order(await service.public_status(status_token))
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.post("/orders/{status_token}/cancel", response_model=PublicOrderStatusResponse)
async def public_cancel(
    status_token: str, service: OnlineOrderingServiceDep
) -> PublicOrderStatusResponse:
    try:
        return PublicOrderStatusResponse.from_order(await service.public_cancel(status_token))
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.get(
    "/{slug}/fulfillment-options", response_model=FulfillmentOptionsResponse
)
async def fulfillment_options(
    slug: str,
    service: OnlineOrderingServiceDep,
    station: str | None = Query(default=None, min_length=20, max_length=200),
) -> FulfillmentOptionsResponse:
    try:
        return await service.fulfillment_options(slug, station)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.get("/{slug}", response_model=PublicOrderingResponse)
async def public_location(
    slug: str,
    service: OnlineOrderingServiceDep,
    station: str | None = Query(default=None, min_length=20, max_length=200),
) -> PublicOrderingResponse:
    try:
        return await service.public_location(slug, station)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.get("/{slug}/menu", response_model=PublicMenuResponse)
async def public_menu(slug: str, service: OnlineOrderingServiceDep) -> PublicMenuResponse:
    try:
        return await service.public_menu(slug)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.get("/{slug}/availability", response_model=AvailabilityResponse)
async def public_availability(
    slug: str,
    service: OnlineOrderingServiceDep,
    station: str | None = Query(default=None, min_length=20, max_length=200),
) -> AvailabilityResponse:
    try:
        return await service.availability(slug, station)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.post("/{slug}/quote", response_model=QuoteResponse)
async def public_quote(
    slug: str,
    payload: QuoteRequest,
    service: OnlineOrderingServiceDep,
    station: str | None = Query(default=None, min_length=20, max_length=200),
) -> QuoteResponse:
    try:
        _station_query(payload.station_token, station)
        return await service.quote(slug, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@public_router.post(
    "/{slug}/orders",
    response_model=PublicOrderCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_order(
    slug: str,
    payload: SubmitOrderRequest,
    service: OnlineOrderingServiceDep,
    station: str | None = Query(default=None, min_length=20, max_length=200),
) -> PublicOrderCreatedResponse:
    try:
        _station_query(payload.station_token, station)
        return PublicOrderCreatedResponse.from_order(await service.submit(slug, payload))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/online-orders", response_model=list[OnlineOrderResponse])
async def list_orders(
    context: OnlineOrdersReadDep,
    service: OnlineOrderingServiceDep,
    location_id: UUID | None = None,
    order_status: Annotated[
        OnlineOrderStatus | None, Query(alias="status")
    ] = None,
) -> list[OnlineOrderResponse]:
    try:
        return await service.list_orders(context, location_id=location_id, status=order_status)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/online-orders/{order_id}", response_model=OnlineOrderResponse)
async def get_order(
    order_id: UUID, context: OnlineOrdersReadDep, service: OnlineOrderingServiceDep
) -> OnlineOrderResponse:
    try:
        return await service.get_order(context, order_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-orders/{order_id}/accept", response_model=OnlineOrderResponse)
async def accept_order(
    order_id: UUID,
    payload: StaffActionRequest,
    context: OnlineOrdersManageDep,
    service: OnlineOrderingServiceDep,
) -> OnlineOrderResponse:
    try:
        return await service.accept(context, order_id, payload.client_action_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-orders/{order_id}/reject", response_model=OnlineOrderResponse)
async def reject_order(
    order_id: UUID,
    payload: StaffActionRequest,
    context: OnlineOrdersManageDep,
    service: OnlineOrderingServiceDep,
) -> OnlineOrderResponse:
    if not payload.reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Reason is required")
    try:
        return await service.reject(
            context, order_id, payload.client_action_id, payload.reason
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-orders/{order_id}/cancel", response_model=OnlineOrderResponse)
async def cancel_order(
    order_id: UUID,
    payload: StaffActionRequest,
    context: OnlineOrdersManageDep,
    service: OnlineOrderingServiceDep,
) -> OnlineOrderResponse:
    if not payload.reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Reason is required")
    try:
        return await service.cancel(
            context,
            order_id,
            payload.client_action_id,
            payload.reason,
            external_refund_confirmed=payload.external_refund_confirmed,
            refund_reference=payload.refund_reference,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-orders/{order_id}/ready", response_model=OnlineOrderResponse)
async def ready_order(
    order_id: UUID,
    payload: StaffActionRequest,
    context: OnlineOrdersManageDep,
    service: OnlineOrderingServiceDep,
) -> OnlineOrderResponse:
    try:
        return await service.ready(context, order_id, payload.client_action_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-orders/{order_id}/complete", response_model=OnlineOrderResponse)
async def complete_order(
    order_id: UUID,
    payload: StaffActionRequest,
    context: OnlineOrdersManageDep,
    service: OnlineOrderingServiceDep,
) -> OnlineOrderResponse:
    try:
        return await service.complete(context, order_id, payload.client_action_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/online-ordering/settings/{location_id}", response_model=LocationSettingsResponse
)
async def get_settings(
    location_id: UUID,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> LocationSettingsResponse:
    try:
        return await service.get_settings(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/online-ordering/settings", response_model=LocationSettingsResponse)
async def save_settings(
    payload: LocationSettingsWrite,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> LocationSettingsResponse:
    try:
        return await service.save_settings(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/online-ordering/zones", response_model=list[DeliveryZoneResponse])
async def list_zones(
    location_id: UUID,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> list[DeliveryZoneResponse]:
    try:
        return await service.list_zones(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/online-ordering/zones",
    response_model=DeliveryZoneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_zone(
    payload: DeliveryZoneWrite,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> DeliveryZoneResponse:
    try:
        return await service.create_zone(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/online-ordering/zones/{zone_id}", response_model=DeliveryZoneResponse
)
async def patch_zone(
    zone_id: UUID,
    payload: DeliveryZonePatch,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> DeliveryZoneResponse:
    try:
        return await service.patch_zone(context, zone_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-ordering/pause", response_model=LocationSettingsResponse)
async def pause(
    payload: PauseRequest,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> LocationSettingsResponse:
    try:
        return await service.pause(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-ordering/resume", response_model=LocationSettingsResponse)
async def resume(
    payload: ResumeRequest,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> LocationSettingsResponse:
    try:
        return await service.resume(context, payload.location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/online-ordering/stations", response_model=list[StationResponse])
async def list_stations(
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
    location_id: UUID | None = None,
) -> list[StationResponse]:
    try:
        return await service.list_stations(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/online-ordering/stations",
    response_model=StationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_station(
    payload: StationCreate,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> StationResponse:
    try:
        return await service.create_station(context, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/online-ordering/stations/{station_id}", response_model=StationResponse)
async def patch_station(
    station_id: UUID,
    payload: StationPatch,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> StationResponse:
    try:
        return await service.patch_station(context, station_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/online-ordering/stations/{station_id}/rotate", response_model=StationResponse)
async def rotate_station(
    station_id: UUID,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> StationResponse:
    try:
        return await service.rotate_station(context, station_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/online-ordering/readiness", response_model=ReadinessResponse)
async def readiness(
    location_id: UUID,
    context: OnlineOrderingManageDep,
    service: OnlineOrderingServiceDep,
) -> ReadinessResponse:
    try:
        return await service.readiness(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/online-ordering/reports/channels", response_model=list[ChannelReportRow])
async def channel_report(
    context: OnlineOrdersReadDep,
    service: OnlineOrderingServiceDep,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[ChannelReportRow]:
    try:
        return await service.channel_report(context, date_from, date_to)
    except Exception as exc:
        raise _http_error(exc) from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OnlineOrderQuoteChanged):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": exc.code,
                "message": str(exc),
                "quote": exc.quote.model_dump(mode="json") if exc.quote else None,
            },
        )
    if isinstance(
        exc,
        (
            OnlineOrderIdempotencyConflict,
            OnlineOrderAlreadyAccepted,
            OnlineFulfillmentUnavailable,
            OnlineFulfillmentSlotUnavailable,
            OnlineOrderCancellationForbidden,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, OnlineOrderingNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, OnlineOrderingUnavailable):
        return HTTPException(
            status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)}
        )
    if isinstance(exc, OnlineOrderingError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": str(exc)},
        )
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")


def _station_query(payload_token: str | None, query_token: str | None) -> None:
    if payload_token != query_token:
        raise OnlineOrderInvalidStation("Ordering station token does not match the request")
