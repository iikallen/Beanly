from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse

from beanly.modules.inventory.api.dependencies import (
    InventoryAdjustDep,
    InventoryCountDep,
    InventoryFullReadDep,
    InventoryMovementDep,
    InventoryOperationsServiceDep,
    InventoryReadDep,
    InventoryServiceDep,
    InventoryTransferDep,
    InventoryWriteDep,
    InventoryWriteOffDep,
)
from beanly.modules.inventory.api.schemas import (
    AdjustmentRequest,
    CreateItemRequest,
    CreateWarehouseRequest,
    GlobalMovementResponse,
    InventoryCountLinesRequest,
    InventoryCountLineUpdate,
    InventoryCountPostRequest,
    InventoryCountRequest,
    InventoryCountResponse,
    InventoryTransferRequest,
    InventoryTransferResponse,
    InventoryValuationResponse,
    ItemResponse,
    MovementRowResponse,
    OpeningBalanceRequest,
    StockRowResponse,
    TransactionDetailResponse,
    TransactionSummaryResponse,
    WarehouseResponse,
    WriteOffReasonPatch,
    WriteOffReasonRequest,
    WriteOffReasonResponse,
    WriteOffRequest,
    WriteOffResponse,
)
from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    CreateInventoryItemCommand,
    CreateWarehouseCommand,
    QuantityInput,
)
from beanly.modules.inventory.application.operations import OperationLineInput
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.exceptions import (
    DuplicateInventoryResource,
    IdempotencyConflict,
    InvalidInventoryOperation,
    InvalidInventoryUnit,
    InventoryCountChanged,
    InventoryNotFound,
    SourceControlledTransaction,
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


@router.get("/movements", response_model=list[GlobalMovementResponse])
async def global_movements(
    context: InventoryMovementDep,
    service: InventoryServiceDep,
    warehouse_id: UUID | None = None,
    location_id: UUID | None = None,
    inventory_item_id: UUID | None = None,
    type: InventoryTransactionType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    reference_type: str | None = None,
) -> list[GlobalMovementResponse]:
    try:
        values = await service.list_global_movements(
            context,
            warehouse_id,
            location_id,
            inventory_item_id,
            type,
            date_from,
            date_to,
            reference_type,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return [GlobalMovementResponse.model_validate(value) for value in values]


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
) -> TransactionDetailResponse | JSONResponse:
    try:
        detail = await service.reverse(context, transaction_id, idempotency_key)
    except SourceControlledTransaction:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "SOURCE_CONTROLLED_TRANSACTION"},
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return TransactionDetailResponse.from_detail(detail)


@router.get("/write-off-reasons", response_model=list[WriteOffReasonResponse])
async def list_writeoff_reasons(
    context: InventoryFullReadDep, service: InventoryOperationsServiceDep
) -> list[WriteOffReasonResponse]:
    return [
        WriteOffReasonResponse.model_validate(value)
        for value in await service.list_reasons(context)
    ]


@router.post(
    "/write-off-reasons",
    response_model=WriteOffReasonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_writeoff_reason(
    payload: WriteOffReasonRequest,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffReasonResponse:
    try:
        value = await service.create_reason(context, payload.name)
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffReasonResponse.model_validate(value)


@router.patch("/write-off-reasons/{reason_id}", response_model=WriteOffReasonResponse)
async def patch_writeoff_reason(
    reason_id: UUID,
    payload: WriteOffReasonPatch,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffReasonResponse:
    try:
        value = await service.update_reason(
            context, reason_id, name=payload.name, is_active=payload.is_active
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffReasonResponse.model_validate(value)


@router.post(
    "/write-off-reasons/{reason_id}/deactivate",
    response_model=WriteOffReasonResponse,
)
async def deactivate_writeoff_reason(
    reason_id: UUID,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffReasonResponse:
    try:
        value = await service.update_reason(context, reason_id, is_active=False)
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffReasonResponse.model_validate(value)


@router.post(
    "/write-offs", response_model=WriteOffResponse, status_code=status.HTTP_201_CREATED
)
async def create_writeoff(
    payload: WriteOffRequest,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffResponse:
    try:
        value = await service.create_writeoff(
            context,
            payload.warehouse_id,
            payload.reason_id,
            payload.occurred_at,
            payload.note,
            _operation_lines(payload.lines),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffResponse.model_validate(value)


@router.get("/write-offs", response_model=list[WriteOffResponse])
async def list_writeoffs(
    context: InventoryFullReadDep, service: InventoryOperationsServiceDep
) -> list[WriteOffResponse]:
    return [
        WriteOffResponse.model_validate(value)
        for value in await service.list_writeoffs(context)
    ]


@router.get("/write-offs/{writeoff_id}", response_model=WriteOffResponse)
async def get_writeoff(
    writeoff_id: UUID,
    context: InventoryFullReadDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffResponse:
    try:
        value = await service.get_writeoff(context, writeoff_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffResponse.model_validate(value)


@router.patch("/write-offs/{writeoff_id}", response_model=WriteOffResponse)
async def patch_writeoff(
    writeoff_id: UUID,
    payload: WriteOffRequest,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffResponse:
    try:
        value = await service.update_writeoff(
            context,
            writeoff_id,
            payload.warehouse_id,
            payload.reason_id,
            payload.occurred_at,
            payload.note,
            _operation_lines(payload.lines),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffResponse.model_validate(value)


@router.post("/write-offs/{writeoff_id}/post", response_model=WriteOffResponse)
async def post_writeoff(
    writeoff_id: UUID,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffResponse:
    try:
        value = await service.post_writeoff(context, writeoff_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffResponse.model_validate(value)


@router.post("/write-offs/{writeoff_id}/reverse", response_model=WriteOffResponse)
async def reverse_writeoff(
    writeoff_id: UUID,
    context: InventoryWriteOffDep,
    service: InventoryOperationsServiceDep,
) -> WriteOffResponse:
    try:
        value = await service.reverse_writeoff(context, writeoff_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return WriteOffResponse.model_validate(value)


@router.post(
    "/counts", response_model=InventoryCountResponse, status_code=status.HTTP_201_CREATED
)
async def create_inventory_count(
    payload: InventoryCountRequest,
    context: InventoryCountDep,
    service: InventoryOperationsServiceDep,
) -> InventoryCountResponse:
    try:
        value = await service.create_count(
            context,
            payload.warehouse_id,
            payload.type,
            tuple(payload.inventory_item_ids),
            payload.note,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryCountResponse.model_validate(value)


@router.get("/counts", response_model=list[InventoryCountResponse])
async def list_inventory_counts(
    context: InventoryFullReadDep, service: InventoryOperationsServiceDep
) -> list[InventoryCountResponse]:
    return [
        InventoryCountResponse.model_validate(value)
        for value in await service.list_counts(context)
    ]


@router.get("/counts/{count_id}", response_model=InventoryCountResponse)
async def get_inventory_count(
    count_id: UUID,
    context: InventoryFullReadDep,
    service: InventoryOperationsServiceDep,
) -> InventoryCountResponse:
    try:
        value = await service.get_count(context, count_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryCountResponse.model_validate(value)


@router.put("/counts/{count_id}/lines", response_model=InventoryCountResponse)
async def update_inventory_count_lines(
    count_id: UUID,
    payload: InventoryCountLinesRequest,
    context: InventoryCountDep,
    service: InventoryOperationsServiceDep,
) -> InventoryCountResponse:
    try:
        value = await service.update_count_lines(
            context,
            count_id,
            tuple(
                OperationLineInput(
                    line.inventory_item_id, line.counted_quantity, line.unit
                )
                for line in payload.lines
            ),
            {line.inventory_item_id: line.unit_cost_amount for line in payload.lines},
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryCountResponse.model_validate(value)


@router.put(
    "/counts/{count_id}/lines/{line_id}", response_model=InventoryCountResponse
)
async def update_inventory_count_line(
    count_id: UUID,
    line_id: UUID,
    payload: InventoryCountLineUpdate,
    context: InventoryCountDep,
    service: InventoryOperationsServiceDep,
) -> InventoryCountResponse:
    try:
        count = await service.get_count(context, count_id)
        line = next((value for value in count.lines if value.id == line_id), None)
        if line is None or line.inventory_item_id != payload.inventory_item_id:
            raise InventoryNotFound
        value = await service.update_count_lines(
            context,
            count_id,
            (
                OperationLineInput(
                    payload.inventory_item_id, payload.counted_quantity, payload.unit
                ),
            ),
            {payload.inventory_item_id: payload.unit_cost_amount},
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryCountResponse.model_validate(value)


@router.post("/counts/{count_id}/post", response_model=InventoryCountResponse)
async def post_inventory_count(
    count_id: UUID,
    payload: InventoryCountPostRequest,
    context: InventoryCountDep,
    service: InventoryOperationsServiceDep,
) -> InventoryCountResponse | JSONResponse:
    try:
        value = await service.post_count(
            context, count_id, payload.confirm_stock_changes
        )
    except InventoryCountChanged as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "INVENTORY_COUNT_CHANGED", "changed_items": exc.changed_items},
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryCountResponse.model_validate(value)


@router.post("/counts/{count_id}/cancel", response_model=InventoryCountResponse)
async def cancel_inventory_count(
    count_id: UUID,
    context: InventoryCountDep,
    service: InventoryOperationsServiceDep,
) -> InventoryCountResponse:
    try:
        value = await service.cancel_count(context, count_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryCountResponse.model_validate(value)


@router.post(
    "/transfers",
    response_model=InventoryTransferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inventory_transfer(
    payload: InventoryTransferRequest,
    context: InventoryTransferDep,
    service: InventoryOperationsServiceDep,
) -> InventoryTransferResponse:
    try:
        value = await service.create_transfer(
            context,
            payload.source_warehouse_id,
            payload.destination_warehouse_id,
            payload.occurred_at,
            payload.note,
            _operation_lines(payload.lines),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryTransferResponse.model_validate(value)


@router.get("/transfers", response_model=list[InventoryTransferResponse])
async def list_inventory_transfers(
    context: InventoryFullReadDep, service: InventoryOperationsServiceDep
) -> list[InventoryTransferResponse]:
    return [
        InventoryTransferResponse.model_validate(value)
        for value in await service.list_transfers(context)
    ]


@router.get("/transfers/{transfer_id}", response_model=InventoryTransferResponse)
async def get_inventory_transfer(
    transfer_id: UUID,
    context: InventoryFullReadDep,
    service: InventoryOperationsServiceDep,
) -> InventoryTransferResponse:
    try:
        value = await service.get_transfer(context, transfer_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryTransferResponse.model_validate(value)


@router.patch("/transfers/{transfer_id}", response_model=InventoryTransferResponse)
async def patch_inventory_transfer(
    transfer_id: UUID,
    payload: InventoryTransferRequest,
    context: InventoryTransferDep,
    service: InventoryOperationsServiceDep,
) -> InventoryTransferResponse:
    try:
        value = await service.update_transfer(
            context,
            transfer_id,
            payload.source_warehouse_id,
            payload.destination_warehouse_id,
            payload.occurred_at,
            payload.note,
            _operation_lines(payload.lines),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryTransferResponse.model_validate(value)


@router.post("/transfers/{transfer_id}/post", response_model=InventoryTransferResponse)
async def post_inventory_transfer(
    transfer_id: UUID,
    context: InventoryTransferDep,
    service: InventoryOperationsServiceDep,
) -> InventoryTransferResponse:
    try:
        value = await service.post_transfer(context, transfer_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryTransferResponse.model_validate(value)


@router.post("/transfers/{transfer_id}/reverse", response_model=InventoryTransferResponse)
async def reverse_inventory_transfer(
    transfer_id: UUID,
    context: InventoryTransferDep,
    service: InventoryOperationsServiceDep,
) -> InventoryTransferResponse:
    try:
        value = await service.reverse_transfer(context, transfer_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return InventoryTransferResponse.model_validate(value)


def _operation_lines(values) -> tuple[OperationLineInput, ...]:
    return tuple(
        OperationLineInput(value.inventory_item_id, value.quantity, value.unit, value.note)
        for value in values
    )


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
