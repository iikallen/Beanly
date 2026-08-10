from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    FinanceSnapshot,
    LocationFinanceRow,
)
from beanly.modules.finance.application.finance_query_service import FinanceQueryService
from beanly.modules.organizations.domain.entities import TenantContext


class FinanceDashboardGateway:
    def __init__(self, service: FinanceQueryService) -> None:
        self.service = service

    async def snapshot(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> FinanceSnapshot:
        pnl = await self.service.pnl(context, date_from, date_to, location_id)
        _, _, _, cash_net = await self.service.cash_flow(
            context, date_from, date_to, location_id
        )
        data_as_of = await self.service.data_as_of(context, location_id)
        return FinanceSnapshot(
            pnl.currency_code,
            pnl.cogs,
            pnl.gross_profit,
            pnl.gross_margin_percent,
            pnl.operating_expenses,
            pnl.inventory_losses,
            pnl.inventory_gains,
            pnl.operating_profit,
            pnl.incomplete_cogs_sales,
            cash_net,
            data_as_of,
        )

    async def locations(
        self, context: TenantContext, date_from: datetime, date_to: datetime
    ) -> tuple[LocationFinanceRow, ...]:
        return tuple(
            LocationFinanceRow(value.location_id, value.operating_profit)
            for value in await self.service.locations(context, date_from, date_to)
            if value.location_id is not None
        )

    async def operating_profit(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> Decimal:
        return (
            await self.service.pnl(context, date_from, date_to, location_id)
        ).operating_profit
