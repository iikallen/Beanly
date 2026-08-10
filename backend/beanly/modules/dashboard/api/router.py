from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.dashboard.api.dependencies import (
    DashboardQueryServiceDep,
    DashboardReadDep,
)
from beanly.modules.dashboard.api.schemas import DashboardOverviewResponse
from beanly.modules.dashboard.application.period_service import InvalidDashboardPeriod
from beanly.modules.dashboard.domain.enums import DashboardPeriod
from beanly.modules.dashboard.domain.exceptions import DashboardLocationNotFound

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverviewResponse)
async def overview(
    context: DashboardReadDep,
    service: DashboardQueryServiceDep,
    period: DashboardPeriod = DashboardPeriod.TODAY,
    location_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> DashboardOverviewResponse:
    try:
        value = await service.overview(
            context, period, location_id, date_from, date_to
        )
    except DashboardLocationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidDashboardPeriod as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return DashboardOverviewResponse.model_validate(value)
