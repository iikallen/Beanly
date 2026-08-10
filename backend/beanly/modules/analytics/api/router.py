from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.analytics.api.dependencies import (
    AnalyticsQueryServiceDep,
    AnalyticsReadDep,
)
from beanly.modules.analytics.api.schemas import (
    ABCAnalyticsResponse,
    AnalyticsOverviewResponse,
    HourAnalyticsResponse,
    InventoryConsumptionResponse,
    LocationAnalyticsResponse,
    MenuEngineeringResponse,
    ProductsAnalyticsResponse,
)
from beanly.modules.analytics.domain.enums import (
    HourMetric,
    ProductGroupBy,
    ProductSort,
)
from beanly.modules.analytics.domain.exceptions import (
    AnalyticsFinancialAccessDenied,
    AnalyticsLocationNotFound,
    InvalidAnalyticsRange,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def overview(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
    location_id: UUID | None = None,
) -> AnalyticsOverviewResponse:
    return AnalyticsOverviewResponse.model_validate(
        await _call(service.overview(context, date_from, date_to, location_id))
    )


@router.get("/products", response_model=ProductsAnalyticsResponse)
async def products(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
    location_id: UUID | None = None,
    group_by: ProductGroupBy = ProductGroupBy.PRODUCT,
    sort_by: ProductSort = ProductSort.REVENUE,
    limit: int = 25,
) -> ProductsAnalyticsResponse:
    return ProductsAnalyticsResponse.model_validate(
        await _call(
            service.products(
                context, date_from, date_to, location_id, group_by, sort_by, limit
            )
        )
    )


@router.get("/products/abc", response_model=ABCAnalyticsResponse)
async def abc(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
    location_id: UUID | None = None,
) -> ABCAnalyticsResponse:
    return ABCAnalyticsResponse.model_validate(
        await _call(service.abc(context, date_from, date_to, location_id))
    )


@router.get("/menu-engineering", response_model=MenuEngineeringResponse)
async def menu_engineering(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
    location_id: UUID | None = None,
) -> MenuEngineeringResponse:
    return MenuEngineeringResponse.model_validate(
        await _call(
            service.menu_engineering(context, date_from, date_to, location_id)
        )
    )


@router.get("/hours", response_model=HourAnalyticsResponse)
async def hours(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
    location_id: UUID | None = None,
    metric: HourMetric = HourMetric.REVENUE,
) -> HourAnalyticsResponse:
    return HourAnalyticsResponse.model_validate(
        await _call(service.hours(context, date_from, date_to, location_id, metric))
    )


@router.get(
    "/inventory-consumption", response_model=InventoryConsumptionResponse
)
async def inventory_consumption(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
    location_id: UUID | None = None,
    warehouse_id: UUID | None = None,
    inventory_item_id: UUID | None = None,
) -> InventoryConsumptionResponse:
    return InventoryConsumptionResponse.model_validate(
        await _call(
            service.inventory_consumption(
                context,
                date_from,
                date_to,
                location_id,
                warehouse_id,
                inventory_item_id,
            )
        )
    )


@router.get("/locations", response_model=LocationAnalyticsResponse)
async def locations(
    context: AnalyticsReadDep,
    service: AnalyticsQueryServiceDep,
    date_from: date,
    date_to: date,
) -> LocationAnalyticsResponse:
    return LocationAnalyticsResponse.model_validate(
        await _call(service.locations(context, date_from, date_to))
    )


async def _call(awaitable):
    try:
        return await awaitable
    except AnalyticsLocationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidAnalyticsRange as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except AnalyticsFinancialAccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
