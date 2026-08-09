from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status

from beanly.modules.inventory.api.dependencies import (
    InventoryAdjustDep,
    InventoryFullReadDep,
    InventoryReadDep,
    InventoryServiceDep,
    InventoryWriteDep,
)
from beanly.modules.inventory.api.schemas import (
    AdjustmentRequest,
    CreateItemRequest,
    CreateWarehouseRequest,
    InventoryValuationResponse,
    ItemResponse,
    MovementRowResponse,
    OpeningBalanceRequest,
    StockRowResponse,
    TransactionDetailResponse,
    TransactionSummaryResponse,
    WarehouseResponse,
)
from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    CreateInventoryItemCommand,
    CreateWarehouseCommand,
    QuantityInput,
)
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.exceptions import (
    DuplicateInventoryResource,
    IdempotencyConflict,
    InvalidInventoryOperation,
    InvalidInventoryUnit,
    InventoryNotFound,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
]


@router.get("/warehouses", response_model=list[WarehouseResponse])
async def list_warehouses(
    context: InventoryReadDep, service: InventoryServiceDep
) -> list[WarehouseResponse]:
    return [
        WarehouseResponse.model_validate(value) for value in await service.list_warehouses(context)
    ]


@router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: CreateWarehouseRequest,
    context: InventoryWriteDep,
    service: InventoryServiceDep,
) -> WarehouseResponse:
    try:
        value = await service.create_warehouse(
            context,
            CreateWarehouseCommand(
                context.organization_id,
                context.user_id,
                payload.location_id,
                payload.name,
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return WarehouseResponse.model_validate(value)


@router.get("/items", response_model=list[ItemResponse])
async def list_items(context: InventoryReadDep, service: InventoryServiceDep) -> list[ItemResponse]:
    return [ItemResponse.model_validate(value) for value in await service.list_items(context)]


@router.post("/items", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: CreateItemRequest,
    context: InventoryWriteDep,
    service: InventoryServiceDep,
) -> ItemResponse:
    try:
        value = await service.create_item(
            context,
            CreateInventoryItemCommand(
                context.organization_id, payload.name, payload.sku, payload.base_unit
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ItemResponse.model_validate(value)


@router.get("/stock", response_model=list[StockRowResponse])
async def list_stock(
    context: InventoryReadDep,
    service: InventoryServiceDep,
    warehouse_id: UUID | None = None,
    location_id: UUID | None = None,
    item_id: UUID | None = None,
) -> list[StockRowResponse]:
    try:
        rows = await service.list_stock(context, warehouse_id, location_id, item_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [StockRowResponse.model_validate(row) for row in rows]


@router.get("/valuation", response_model=InventoryValuationResponse)
async def inventory_valuation(
    context: InventoryFullReadDep,
    service: InventoryServiceDep,
    warehouse_id: UUID | None = None,
    location_id: UUID | None = None,
) -> InventoryValuationResponse:
    try:
        valuation = await service.valuation(context, warehouse_id, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryValuationResponse.model_validate(valuation)


@router.get("/items/{item_id}/stock", response_model=StockRowResponse)
async def item_stock(
    item_id: UUID,
    warehouse_id: Annotated[UUID, Query()],
    context: InventoryReadDep,
    service: InventoryServiceDep,
) -> StockRowResponse:
    try:
        row = await service.get_item_stock(context, item_id, warehouse_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return StockRowResponse.model_validate(row)


@router.get("/items/{item_id}/movements", response_model=list[MovementRowResponse])
async def item_movements(
    item_id: UUID,
    context: InventoryFullReadDep,
    service: InventoryServiceDep,
    warehouse_id: UUID | None = None,
) -> list[MovementRowResponse]:
    try:
        rows = await service.list_movements(context, item_id, warehouse_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [MovementRowResponse.model_validate(row) for row in rows]


@router.get("/transactions", response_model=list[TransactionSummaryResponse])
async def list_transactions(
    context: InventoryFullReadDep, service: InventoryServiceDep
) -> list[TransactionSummaryResponse]:
    return [
        TransactionSummaryResponse.model_validate(value)
        for value in await service.list_transactions(context)
    ]


@router.get("/transactions/{transaction_id}", response_model=TransactionDetailResponse)
async def get_transaction(
    transaction_id: UUID,
    context: InventoryFullReadDep,
    service: InventoryServiceDep,
) -> TransactionDetailResponse:
    try:
        detail = await service.get_transaction(context, transaction_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return TransactionDetailResponse.from_detail(detail)


@router.post(
    "/adjustments",
    response_model=TransactionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def adjustment(
    payload: AdjustmentRequest,
    context: InventoryAdjustDep,
    service: InventoryServiceDep,
    idempotency_key: IdempotencyKey = None,
) -> TransactionDetailResponse:
    command = CreateAndPostCommand(
        context.organization_id,
        context.user_id,
        payload.warehouse_id,
        InventoryTransactionType.ADJUSTMENT,
        payload.reason,
        tuple(
            QuantityInput(
                line.inventory_item_id,
                line.quantity,
                line.unit_code,
                line.unit_cost_amount,
            )
            for line in payload.lines
        ),
        idempotency_key,
    )
    try:
        detail = await service.create_and_post(context, command)
    except Exception as exc:
        raise _http_error(exc) from exc
    return TransactionDetailResponse.from_detail(detail)


@router.post(
    "/opening-balances",
    response_model=TransactionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def opening_balance(
    payload: OpeningBalanceRequest,
    context: InventoryAdjustDep,
    service: InventoryServiceDep,
    idempotency_key: IdempotencyKey = None,
) -> TransactionDetailResponse:
    command = CreateAndPostCommand(
        context.organization_id,
        context.user_id,
        payload.warehouse_id,
        InventoryTransactionType.OPENING_BALANCE,
        "Opening balance",
        tuple(
            QuantityInput(
                line.inventory_item_id,
                line.quantity,
                line.unit_code,
                line.unit_cost_amount,
            )
            for line in payload.items
        ),
        idempotency_key,
    )
    try:
        detail = await service.create_and_post(context, command)
    except Exception as exc:
        raise _http_error(exc) from exc
    return TransactionDetailResponse.from_detail(detail)


@router.post(
    "/transactions/{transaction_id}/reverse",
    response_model=TransactionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reverse_transaction(
    transaction_id: UUID,
    context: InventoryAdjustDep,
    service: InventoryServiceDep,
    idempotency_key: IdempotencyKey = None,
) -> TransactionDetailResponse:
    try:
        detail = await service.reverse(context, transaction_id, idempotency_key)
    except Exception as exc:
        raise _http_error(exc) from exc
    return TransactionDetailResponse.from_detail(detail)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InventoryNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Inventory resource not found")
    if isinstance(exc, InvalidInventoryUnit):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(
        exc,
        (DuplicateInventoryResource, IdempotencyConflict, InvalidInventoryOperation),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc) or "Inventory conflict")
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    raise exc
