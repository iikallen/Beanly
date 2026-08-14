from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from beanly.modules.kitchen.api.dependencies import (
    KitchenExpoDep,
    KitchenManageDep,
    KitchenReadDep,
    KitchenReportDep,
    KitchenServiceDep,
    KitchenWorkDep,
)
from beanly.modules.kitchen.api.schemas import (
    ActionRequest,
    BoardResponse,
    PerformanceRow,
    ReadinessResponse,
    RoutingCreate,
    RoutingResponse,
    StationCreate,
    StationPatch,
    StationResponse,
    TicketResponse,
    WorkItemResponse,
)
from beanly.modules.kitchen.domain.enums import KitchenStationRole
from beanly.modules.kitchen.domain.exceptions import (
    KitchenActionIdempotencyConflict,
    KitchenError,
    KitchenInvalid,
    KitchenNotFound,
    KitchenWorkNotReady,
)

router = APIRouter(prefix="/kitchen", tags=["kitchen"])


@router.get("/stations", response_model=list[StationResponse])
async def list_stations(location_id: UUID, context: KitchenReadDep, service: KitchenServiceDep):
    try:
        return [
            StationResponse.from_model(value)
            for value in await service.list_stations(context, location_id)
        ]
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/stations", response_model=StationResponse, status_code=status.HTTP_201_CREATED)
async def create_station(
    payload: StationCreate, context: KitchenManageDep, service: KitchenServiceDep
):
    try:
        return StationResponse.from_model(await service.create_station(context, payload))
    except Exception as exc:
        raise _http(exc) from exc


@router.patch("/stations/{station_id}", response_model=StationResponse)
async def update_station(
    station_id: UUID, payload: StationPatch, context: KitchenManageDep, service: KitchenServiceDep
):
    try:
        return StationResponse.from_model(
            await service.update_station(context, station_id, payload)
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/routing", response_model=list[RoutingResponse])
async def list_routing(location_id: UUID, context: KitchenReadDep, service: KitchenServiceDep):
    try:
        return [
            RoutingResponse.from_model(value)
            for value in await service.list_routing(context, location_id)
        ]
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/routing", response_model=RoutingResponse, status_code=status.HTTP_201_CREATED)
async def create_routing(
    payload: RoutingCreate, context: KitchenManageDep, service: KitchenServiceDep
):
    try:
        return RoutingResponse.from_model(await service.create_routing(context, payload))
    except Exception as exc:
        raise _http(exc) from exc


@router.delete("/routing/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routing(rule_id: UUID, context: KitchenManageDep, service: KitchenServiceDep):
    try:
        await service.delete_routing(context, rule_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/stations/{station_id}/board", response_model=BoardResponse)
async def station_board(
    station_id: UUID,
    context: KitchenReadDep,
    service: KitchenServiceDep,
    after_version: int | None = Query(default=None, ge=0),
):
    try:
        station, tickets, cursor = await service.board(context, station_id, after_version)
        whole = station.role in {KitchenStationRole.EXPO, KitchenStationRole.PREP_EXPO}
        return BoardResponse(
            station=StationResponse.from_model(station),
            cursor=cursor,
            server_time=datetime.now(UTC),
            tickets=[
                TicketResponse.from_model(ticket, station_id=station.id, whole_order=whole)
                for ticket in tickets
            ],
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: UUID, context: KitchenReadDep, service: KitchenServiceDep):
    try:
        return TicketResponse.from_model(await service.get_ticket(context, ticket_id))
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/work-items/{work_item_id}/start", response_model=WorkItemResponse)
async def start_work(
    work_item_id: UUID, payload: ActionRequest, context: KitchenWorkDep, service: KitchenServiceDep
):
    try:
        return WorkItemResponse.from_model(
            await service.start_work(context, work_item_id, payload.client_action_id)
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/work-items/{work_item_id}/ready", response_model=WorkItemResponse)
async def ready_work(
    work_item_id: UUID, payload: ActionRequest, context: KitchenWorkDep, service: KitchenServiceDep
):
    try:
        return WorkItemResponse.from_model(
            await service.ready_work(context, work_item_id, payload.client_action_id)
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/tickets/{ticket_id}/complete", response_model=TicketResponse)
async def complete_ticket(
    ticket_id: UUID, payload: ActionRequest, context: KitchenExpoDep, service: KitchenServiceDep
):
    try:
        return TicketResponse.from_model(
            await service.complete_ticket(context, ticket_id, payload.client_action_id)
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/tickets/{ticket_id}/recall", response_model=TicketResponse)
async def recall_ticket(
    ticket_id: UUID, payload: ActionRequest, context: KitchenExpoDep, service: KitchenServiceDep
):
    try:
        return TicketResponse.from_model(
            await service.recall_ticket(context, ticket_id, payload.client_action_id)
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/readiness", response_model=ReadinessResponse)
async def readiness(location_id: UUID, context: KitchenReadDep, service: KitchenServiceDep):
    try:
        value = await service.readiness(context, location_id)
        return ReadinessResponse(
            **{name: value[name] for name in ("ready", "active_stations", "unrouted_variants")},
            default_station=StationResponse.from_model(value["default_station"])
            if value["default_station"]
            else None,
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/reports/performance", response_model=list[PerformanceRow])
async def performance(
    context: KitchenReportDep,
    service: KitchenServiceDep,
    location_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    try:
        return [
            PerformanceRow.model_validate(value)
            for value in await service.performance(
                context, location_id=location_id, date_from=date_from, date_to=date_to
            )
        ]
    except Exception as exc:
        raise _http(exc) from exc


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KitchenNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, (KitchenActionIdempotencyConflict, KitchenWorkNotReady)):
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, (KitchenInvalid, KitchenError, IntegrityError)):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": getattr(exc, "code", "INVALID_KITCHEN"), "message": str(exc)},
        )
    return HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        {"code": "INTERNAL_ERROR", "message": "Kitchen operation failed"},
    )
