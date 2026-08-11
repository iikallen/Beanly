from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from beanly.modules.identity.api.dependencies import OriginDep
from beanly.modules.offline_pos.api.dependencies import (
    ActiveDeviceDep,
    DeviceManageDep,
    DeviceServiceDep,
    SessionServiceDep,
    SyncServiceDep,
)
from beanly.modules.offline_pos.api.schemas import (
    CatalogSnapshotResponse,
    DevicePairRequest,
    DeviceResponse,
    OfflineSessionResponse,
    OfflineSyncRequest,
    OfflineSyncResponse,
    PingResponse,
    SessionStartRequest,
)
from beanly.modules.offline_pos.application.device_service import credential_hash
from beanly.modules.offline_pos.domain.exceptions import (
    ActiveDeviceExists,
    OfflinePosConflict,
    OfflinePosNotFound,
    OfflinePosUnauthorized,
)
from beanly.modules.organizations.api.dependencies import TenantContextDep

router = APIRouter(prefix="/pos/offline", tags=["offline-pos"])
_COOKIE = "beanly_pos_device"
_COOKIE_PATH = "/api/v1/pos/offline"


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(context: DeviceManageDep, service: DeviceServiceDep) -> list[DeviceResponse]:
    return [DeviceResponse.model_validate(value) for value in await service.list(context)]


@router.post("/devices/pair", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def pair_device(
    payload: DevicePairRequest,
    response: Response,
    context: DeviceManageDep,
    service: DeviceServiceDep,
    origin: OriginDep,
) -> DeviceResponse:
    del origin
    try:
        device, credential = await service.pair(context, payload.register_id, payload.name)
    except Exception as exc:
        raise _http_error(exc) from exc
    response.set_cookie(
        _COOKIE,
        credential,
        httponly=True,
        secure=True,
        samesite="strict",
        path=_COOKIE_PATH,
        max_age=60 * 60 * 24 * 365,
    )
    return DeviceResponse.model_validate(device)


@router.post("/devices/{device_id}/revoke", response_model=DeviceResponse)
async def revoke_device(
    device_id: UUID,
    request: Request,
    response: Response,
    context: DeviceManageDep,
    service: DeviceServiceDep,
    origin: OriginDep,
) -> DeviceResponse:
    del origin
    try:
        device = await service.revoke(context, device_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    caller_credential = request.cookies.get(_COOKIE)
    if caller_credential and credential_hash(caller_credential) == device.credential_hash:
        response.delete_cookie(
            _COOKIE, path=_COOKIE_PATH, secure=True, samesite="strict"
        )
    return DeviceResponse.model_validate(device)


@router.post("/sessions/start", response_model=OfflineSessionResponse, status_code=201)
async def start_session(
    payload: SessionStartRequest,
    context: TenantContextDep,
    device: ActiveDeviceDep,
    service: SessionServiceDep,
    origin: OriginDep,
) -> OfflineSessionResponse:
    del origin
    try:
        value, snapshot = await service.start(context, device, payload.shift_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _session_response(value, snapshot)


@router.get("/sessions/current", response_model=OfflineSessionResponse | None)
async def current_session(
    device: ActiveDeviceDep, service: SessionServiceDep
) -> OfflineSessionResponse | None:
    try:
        result = await service.current(device)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _session_response(*result) if result else None


@router.post("/sessions/{session_id}/refresh", response_model=OfflineSessionResponse)
async def refresh_session(
    session_id: UUID,
    device: ActiveDeviceDep,
    service: SessionServiceDep,
    origin: OriginDep,
) -> OfflineSessionResponse:
    del origin
    try:
        result = await service.refresh(device, session_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _session_response(*result)


@router.post("/sessions/{session_id}/close", response_model=OfflineSessionResponse)
async def close_session(
    session_id: UUID,
    device: ActiveDeviceDep,
    service: SessionServiceDep,
    origin: OriginDep,
) -> OfflineSessionResponse:
    del origin
    try:
        result = await service.close(device, session_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _session_response(*result)


@router.post("/sync", response_model=OfflineSyncResponse)
async def sync(
    payload: OfflineSyncRequest,
    device: ActiveDeviceDep,
    service: SyncServiceDep,
    origin: OriginDep,
) -> OfflineSyncResponse:
    del origin
    try:
        results = await service.sync(device, payload)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OfflineSyncResponse(server_time=datetime.now(UTC), results=results)


@router.get("/ping", response_model=PingResponse)
async def ping(device: ActiveDeviceDep) -> PingResponse:
    del device
    return PingResponse(server_time=datetime.now(UTC))


def _session_response(value, snapshot) -> OfflineSessionResponse:
    return OfflineSessionResponse(
        id=value.id,
        device_id=value.device_id,
        organization_id=value.organization_id,
        location_id=value.location_id,
        register_id=value.register_id,
        shift_id=value.shift_id,
        warehouse_id=value.warehouse_id,
        actor_user_id=value.actor_user_id,
        catalog_snapshot_id=value.catalog_snapshot_id,
        status=value.status,
        started_at=value.started_at,
        expires_at=value.expires_at,
        last_sync_at=value.last_sync_at,
        closed_at=value.closed_at,
        server_time=datetime.now(UTC),
        catalog_snapshot=CatalogSnapshotResponse(
            id=snapshot.id,
            created_at=snapshot.created_at,
            expires_at=snapshot.expires_at,
            payload_hash=snapshot.payload_hash,
            payload=snapshot.public_payload,
        ),
    )


def _http_error(exc: Exception) -> HTTPException:
    detail = {"code": getattr(exc, "code", "OFFLINE_POS_ERROR"), "message": str(exc)}
    if isinstance(exc, (OfflinePosUnauthorized,)):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)
    if isinstance(exc, OfflinePosNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, (OfflinePosConflict, ActiveDeviceExists, IntegrityError)):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    raise exc
