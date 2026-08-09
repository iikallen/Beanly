from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from beanly.modules.organizations.domain.exceptions import (
    InvalidLocationAccess,
    OrganizationAccessDenied,
)
from beanly.modules.sales.api.dependencies import (
    OrderServiceDep,
    RegisterServiceDep,
    SalesCancelDep,
    SalesCreateDep,
    SalesReadDep,
    SalesRegisterManageDep,
    SalesRegisterReadDep,
    SalesShiftManageDep,
    ShiftServiceDep,
)
from beanly.modules.sales.api.schemas import (
    OrderCancelRequest,
    OrderCreateRequest,
    OrderItemConfigurationRequest,
    OrderItemCreateRequest,
    OrderItemPatchRequest,
    OrderPatchRequest,
    OrderResponse,
    RegisterCreateRequest,
    RegisterPatchRequest,
    RegisterResponse,
    ShiftOpenRequest,
    ShiftResponse,
    WarehouseChoiceResponse,
)
from beanly.modules.sales.application.commands import (
    AddOrderItemInput,
    CreateOrderInput,
)
from beanly.modules.sales.domain.enums import OrderStatus
from beanly.modules.sales.domain.exceptions import (
    InvalidModifierRecipe,
    InvalidModifierSelection,
    InvalidSalesOperation,
    OrderImmutable,
    ProductUnavailable,
    SalesAccessDenied,
    SalesConflict,
    SalesNotFound,
)

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post(
    "/registers",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_register(
    payload: RegisterCreateRequest,
    context: SalesRegisterManageDep,
    service: RegisterServiceDep,
) -> RegisterResponse:
    try:
        value = await service.create(context, payload.location_id, payload.name)
    except Exception as exc:
        raise _http_error(exc) from exc
    return RegisterResponse.model_validate(value)


@router.get("/registers", response_model=list[RegisterResponse])
async def list_registers(
    context: SalesRegisterReadDep,
    service: RegisterServiceDep,
    location_id: UUID | None = None,
) -> list[RegisterResponse]:
    try:
        values = await service.list(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [RegisterResponse.model_validate(value) for value in values]


@router.patch("/registers/{register_id}", response_model=RegisterResponse)
async def update_register(
    register_id: UUID,
    payload: RegisterPatchRequest,
    context: SalesRegisterManageDep,
    service: RegisterServiceDep,
) -> RegisterResponse:
    try:
        value = await service.update(context, register_id, payload.name)
    except Exception as exc:
        raise _http_error(exc) from exc
    return RegisterResponse.model_validate(value)


@router.post("/registers/{register_id}/deactivate", response_model=RegisterResponse)
async def deactivate_register(
    register_id: UUID,
    context: SalesRegisterManageDep,
    service: RegisterServiceDep,
) -> RegisterResponse:
    try:
        value = await service.deactivate(context, register_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return RegisterResponse.model_validate(value)


@router.get("/warehouses", response_model=list[WarehouseChoiceResponse])
async def list_warehouses(
    location_id: UUID,
    context: SalesShiftManageDep,
    service: ShiftServiceDep,
) -> list[WarehouseChoiceResponse]:
    try:
        values = await service.list_warehouses(context, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [WarehouseChoiceResponse.model_validate(value) for value in values]


@router.post(
    "/shifts/open",
    response_model=ShiftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_shift(
    payload: ShiftOpenRequest,
    context: SalesShiftManageDep,
    service: ShiftServiceDep,
) -> ShiftResponse:
    try:
        value = await service.open(context, payload.register_id, payload.warehouse_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ShiftResponse.model_validate(value)


@router.get("/shifts/current", response_model=ShiftResponse | None)
async def current_shift(
    register_id: UUID,
    context: SalesShiftManageDep,
    service: ShiftServiceDep,
) -> ShiftResponse | None:
    try:
        value = await service.current(context, register_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ShiftResponse.model_validate(value) if value is not None else None


@router.post("/shifts/{shift_id}/close", response_model=ShiftResponse)
async def close_shift(
    shift_id: UUID,
    context: SalesShiftManageDep,
    service: ShiftServiceDep,
) -> ShiftResponse:
    try:
        value = await service.close(context, shift_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ShiftResponse.model_validate(value)


@router.post(
    "/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED
)
async def create_order(
    payload: OrderCreateRequest,
    context: SalesCreateDep,
    service: OrderServiceDep,
) -> OrderResponse:
    try:
        value = await service.create(
            context,
            CreateOrderInput(
                payload.client_order_id,
                payload.shift_id,
                payload.order_type,
                payload.guest_count,
                payload.table_label,
                payload.note,
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    context: SalesReadDep,
    service: OrderServiceDep,
    location_id: UUID | None = None,
    shift_id: UUID | None = None,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> list[OrderResponse]:
    try:
        values = await service.list(
            context,
            location_id=location_id,
            shift_id=shift_id,
            status=status_filter,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return [OrderResponse.from_entity(value) for value in values]


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    context: SalesReadDep,
    service: OrderServiceDep,
) -> OrderResponse:
    try:
        value = await service.get(context, order_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.patch("/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: UUID,
    payload: OrderPatchRequest,
    context: SalesCreateDep,
    service: OrderServiceDep,
) -> OrderResponse:
    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields supplied")
    try:
        value = await service.update(
            context,
            order_id,
            order_type=payload.order_type,
            guest_count=payload.guest_count,
            guest_count_set="guest_count" in fields,
            table_label=payload.table_label,
            table_label_set="table_label" in fields,
            note=payload.note,
            note_set="note" in fields,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    payload: OrderCancelRequest,
    context: SalesCancelDep,
    service: OrderServiceDep,
) -> OrderResponse:
    try:
        value = await service.cancel(context, order_id, payload.reason)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.post(
    "/orders/{order_id}/items",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_order_item(
    order_id: UUID,
    payload: OrderItemCreateRequest,
    context: SalesCreateDep,
    service: OrderServiceDep,
) -> OrderResponse:
    try:
        value = await service.add_item(
            context,
            order_id,
            AddOrderItemInput(
                payload.client_item_id,
                payload.variant_id,
                tuple(payload.selected_option_ids),
                payload.quantity,
                payload.note,
            ),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.patch("/orders/{order_id}/items/{item_id}", response_model=OrderResponse)
async def update_order_item(
    order_id: UUID,
    item_id: UUID,
    payload: OrderItemPatchRequest,
    context: SalesCreateDep,
    service: OrderServiceDep,
) -> OrderResponse:
    fields = payload.model_fields_set
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No fields supplied")
    try:
        value = await service.update_item(
            context,
            order_id,
            item_id,
            quantity=payload.quantity,
            note=payload.note,
            note_set="note" in fields,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.put(
    "/orders/{order_id}/items/{item_id}/configuration",
    response_model=OrderResponse,
)
async def configure_order_item(
    order_id: UUID,
    item_id: UUID,
    payload: OrderItemConfigurationRequest,
    context: SalesCreateDep,
    service: OrderServiceDep,
) -> OrderResponse:
    try:
        value = await service.reconfigure_item(
            context, order_id, item_id, tuple(payload.selected_option_ids)
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


@router.delete("/orders/{order_id}/items/{item_id}", response_model=OrderResponse)
async def remove_order_item(
    order_id: UUID,
    item_id: UUID,
    context: SalesCreateDep,
    service: OrderServiceDep,
) -> OrderResponse:
    try:
        value = await service.remove_item(context, order_id, item_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return OrderResponse.from_entity(value)


def _http_error(exc: Exception) -> HTTPException:
    detail = {
        "code": getattr(exc, "code", "SALES_ERROR"),
        "message": str(exc) or "Sales operation failed",
    }
    if isinstance(exc, SalesNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(
        exc,
        (
            SalesAccessDenied,
            OrganizationAccessDenied,
            InvalidLocationAccess,
        ),
    ):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail)
    if isinstance(
        exc,
        (
            ProductUnavailable,
            InvalidModifierSelection,
            InvalidModifierRecipe,
            ValueError,
        ),
    ):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(
        exc,
        (
            SalesConflict,
            OrderImmutable,
            InvalidSalesOperation,
            IntegrityError,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    raise exc
