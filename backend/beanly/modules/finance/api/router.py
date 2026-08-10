from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.finance.api.dependencies import (
    CashServiceDep,
    ExpenseServiceDep,
    FinanceQueryServiceDep,
    FinanceReadDep,
    FinanceWriteDep,
)
from beanly.modules.finance.api.schemas import (
    CashAccountPatch,
    CashAccountRequest,
    CashAccountResponse,
    CashFlowResponse,
    CashFlowSectionResponse,
    CashMovementRequest,
    CashMovementResponse,
    DataQualityResponse,
    ExpenseBreakdownRow,
    ExpenseCategoryPatch,
    ExpenseCategoryRequest,
    ExpenseCategoryResponse,
    ExpensePatch,
    ExpenseRequest,
    ExpenseResponse,
    FinanceEntryResponse,
    LocationPnlResponse,
    PnlBreakdownResponse,
    PnlResponse,
)
from beanly.modules.finance.domain.entities import CashAccount, CashMovement, Expense
from beanly.modules.finance.domain.enums import FinanceEntryType
from beanly.modules.finance.domain.exceptions import (
    FinanceError,
    FinanceNotFound,
)

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/pnl", response_model=PnlResponse)
async def pnl(
    context: FinanceReadDep,
    service: FinanceQueryServiceDep,
    date_from: datetime,
    date_to: datetime,
    location_id: UUID | None = None,
) -> PnlResponse:
    try:
        value = await service.pnl(context, date_from, date_to, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return PnlResponse(
        currency_code=value.currency_code,
        revenue=value.revenue,
        cogs=value.cogs,
        gross_profit=value.gross_profit,
        inventory_losses=value.inventory_losses,
        inventory_gains=value.inventory_gains,
        operating_expenses=value.operating_expenses,
        other_income=value.other_income,
        other_expenses=value.other_expenses,
        operating_profit=value.operating_profit,
        gross_margin_percent=value.gross_margin_percent,
        data_quality=DataQualityResponse(
            cogs_complete=value.incomplete_cogs_sales == 0,
            incomplete_cogs_sales=value.incomplete_cogs_sales,
        ),
    )


@router.get("/pnl/breakdown", response_model=PnlBreakdownResponse)
async def pnl_breakdown(
    context: FinanceReadDep,
    service: FinanceQueryServiceDep,
    date_from: datetime,
    date_to: datetime,
    location_id: UUID | None = None,
) -> PnlBreakdownResponse:
    try:
        values = await service.expense_breakdown(context, date_from, date_to, location_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return PnlBreakdownResponse(
        currency_code=await service.repository.currency(context.organization_id),
        operating_expenses=[
            ExpenseBreakdownRow(category_id=category_id, name=name, amount=amount)
            for category_id, name, amount in values
        ],
    )


@router.get("/pnl/locations", response_model=list[LocationPnlResponse])
async def pnl_locations(
    context: FinanceReadDep,
    service: FinanceQueryServiceDep,
    date_from: datetime,
    date_to: datetime,
) -> list[LocationPnlResponse]:
    try:
        values = await service.locations(context, date_from, date_to)
    except Exception as exc:
        raise _http_error(exc) from exc
    return [LocationPnlResponse.model_validate(value, from_attributes=True) for value in values]


@router.get("/cash-flow", response_model=CashFlowResponse)
async def cash_flow(
    context: FinanceReadDep,
    service: FinanceQueryServiceDep,
    date_from: datetime,
    date_to: datetime,
    location_id: UUID | None = None,
) -> CashFlowResponse:
    try:
        currency, opening, values, net = await service.cash_flow(
            context, date_from, date_to, location_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc

    def section(name: str) -> CashFlowSectionResponse:
        inflows, outflows = values.get(name, (0, 0))
        return CashFlowSectionResponse(
            inflows_minor=str(inflows),
            outflows_minor=str(outflows),
            net_minor=str(inflows - outflows),
        )

    return CashFlowResponse(
        currency_code=currency,
        opening_cash_minor=str(opening),
        operating=section("OPERATING"),
        investing=section("INVESTING"),
        financing=section("FINANCING"),
        net_cash_movement_minor=str(net),
        closing_cash_minor=str(opening + net),
    )


@router.get("/expense-categories", response_model=list[ExpenseCategoryResponse])
async def list_categories(
    context: FinanceReadDep, service: ExpenseServiceDep
) -> list[ExpenseCategoryResponse]:
    return [
        ExpenseCategoryResponse.model_validate(value)
        for value in await service.list_categories(context)
    ]


@router.post(
    "/expense-categories",
    response_model=ExpenseCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: ExpenseCategoryRequest,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseCategoryResponse:
    try:
        value = await service.create_category(context, payload.name, payload.sort_order)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExpenseCategoryResponse.model_validate(value)


@router.patch(
    "/expense-categories/{category_id}", response_model=ExpenseCategoryResponse
)
async def update_category(
    category_id: UUID,
    payload: ExpenseCategoryPatch,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseCategoryResponse:
    try:
        current = next(
            (
                value
                for value in await service.list_categories(context)
                if value.id == category_id
            ),
            None,
        )
        if current is None:
            raise FinanceNotFound("Expense category not found")
        value = await service.update_category(
            context,
            category_id,
            payload.name if payload.name is not None else current.name,
            payload.sort_order if payload.sort_order is not None else current.sort_order,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExpenseCategoryResponse.model_validate(value)


@router.post(
    "/expense-categories/{category_id}/deactivate",
    response_model=ExpenseCategoryResponse,
)
async def deactivate_category(
    category_id: UUID,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseCategoryResponse:
    try:
        value = await service.deactivate_category(context, category_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return ExpenseCategoryResponse.model_validate(value)


@router.get("/expenses", response_model=list[ExpenseResponse])
async def list_expenses(
    context: FinanceReadDep, service: ExpenseServiceDep
) -> list[ExpenseResponse]:
    return [_expense(value) for value in await service.list(context)]


@router.get("/expenses/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: UUID, context: FinanceReadDep, service: ExpenseServiceDep
) -> ExpenseResponse:
    try:
        return _expense(await service.get(context, expense_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/expenses", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED
)
async def create_expense(
    payload: ExpenseRequest,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseResponse:
    try:
        value = await service.create(
            context,
            payload.category_id,
            int(payload.amount_minor),
            payload.occurred_at,
            payload.location_id,
            payload.cash_account_id,
            payload.vendor,
            payload.description,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return _expense(value)


@router.patch("/expenses/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    expense_id: UUID,
    payload: ExpensePatch,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseResponse:
    try:
        current = await service.get(context, expense_id)
        fields = payload.model_fields_set
        value = await service.update(
            context,
            expense_id,
            payload.category_id or current.category_id,
            int(payload.amount_minor) if payload.amount_minor else current.amount_minor,
            payload.occurred_at or current.occurred_at,
            payload.location_id if "location_id" in fields else current.location_id,
            (
                payload.cash_account_id
                if "cash_account_id" in fields
                else current.cash_account_id
            ),
            payload.vendor if "vendor" in fields else current.vendor,
            payload.description if "description" in fields else current.description,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return _expense(value)


@router.post("/expenses/{expense_id}/post", response_model=ExpenseResponse)
async def post_expense(
    expense_id: UUID,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseResponse:
    try:
        value = await service.post(context, expense_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _expense(value)


@router.post("/expenses/{expense_id}/reverse", response_model=ExpenseResponse)
async def reverse_expense(
    expense_id: UUID,
    context: FinanceWriteDep,
    service: ExpenseServiceDep,
) -> ExpenseResponse:
    try:
        value = await service.reverse(context, expense_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _expense(value)


@router.get("/accounts", response_model=list[CashAccountResponse])
async def list_accounts(
    context: FinanceReadDep, service: CashServiceDep
) -> list[CashAccountResponse]:
    return [_account(value) for value in await service.list_accounts(context)]


@router.post(
    "/accounts", response_model=CashAccountResponse, status_code=status.HTTP_201_CREATED
)
async def create_account(
    payload: CashAccountRequest,
    context: FinanceWriteDep,
    service: CashServiceDep,
) -> CashAccountResponse:
    try:
        value = await service.create_account(
            context,
            payload.name,
            payload.type,
            payload.location_id,
            int(payload.opening_balance_minor),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return _account(value)


@router.patch("/accounts/{account_id}", response_model=CashAccountResponse)
async def update_account(
    account_id: UUID,
    payload: CashAccountPatch,
    context: FinanceWriteDep,
    service: CashServiceDep,
) -> CashAccountResponse:
    try:
        current = next(
            (value for value in await service.list_accounts(context) if value.id == account_id),
            None,
        )
        if current is None:
            raise FinanceNotFound("Cash account not found")
        value = await service.update_account(
            context,
            account_id,
            payload.name if payload.name is not None else current.name,
            payload.type if payload.type is not None else current.type,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return _account(value)


@router.post("/accounts/{account_id}/deactivate", response_model=CashAccountResponse)
async def deactivate_account(
    account_id: UUID,
    context: FinanceWriteDep,
    service: CashServiceDep,
) -> CashAccountResponse:
    try:
        return _account(await service.deactivate_account(context, account_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/cash-movements", response_model=list[CashMovementResponse])
async def list_cash_movements(
    context: FinanceReadDep, service: CashServiceDep
) -> list[CashMovementResponse]:
    return [_movement(value) for value in await service.list_movements(context)]


@router.post(
    "/cash-movements",
    response_model=CashMovementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cash_movement(
    payload: CashMovementRequest,
    context: FinanceWriteDep,
    service: CashServiceDep,
) -> CashMovementResponse:
    try:
        value = await service.create_movement(
            context,
            payload.type,
            int(payload.amount_minor),
            payload.occurred_at,
            payload.from_account_id,
            payload.to_account_id,
            payload.cash_flow_activity,
            payload.description,
            payload.location_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return _movement(value)


@router.post(
    "/cash-movements/{movement_id}/reverse", response_model=CashMovementResponse
)
async def reverse_cash_movement(
    movement_id: UUID,
    context: FinanceWriteDep,
    service: CashServiceDep,
) -> CashMovementResponse:
    try:
        return _movement(await service.reverse_movement(context, movement_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/entries", response_model=list[FinanceEntryResponse])
async def entries(
    context: FinanceReadDep,
    service: FinanceQueryServiceDep,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    location_id: UUID | None = None,
    entry_type: FinanceEntryType | None = None,
    source_type: str | None = None,
    source_id: UUID | None = None,
) -> list[FinanceEntryResponse]:
    try:
        values = await service.entries(
            context,
            date_from,
            date_to,
            location_id,
            entry_type,
            source_type,
            source_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return [FinanceEntryResponse.model_validate(value) for value in values]


def _expense(value: Expense) -> ExpenseResponse:
    data = {
        field: getattr(value, field)
        for field in ExpenseResponse.model_fields
        if field != "amount_minor"
    }
    return ExpenseResponse(**data, amount_minor=str(value.amount_minor))


def _account(value: CashAccount) -> CashAccountResponse:
    data = {
        field: getattr(value, field)
        for field in CashAccountResponse.model_fields
        if field not in {"opening_balance_minor", "balance_minor"}
    }
    return CashAccountResponse(
        **data,
        opening_balance_minor=str(value.opening_balance_minor),
        balance_minor=str(value.balance_minor),
    )


def _movement(value: CashMovement) -> CashMovementResponse:
    data = {
        field: getattr(value, field)
        for field in CashMovementResponse.model_fields
        if field != "amount_minor"
    }
    return CashMovementResponse(**data, amount_minor=str(value.amount_minor))


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FinanceNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, FinanceError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Finance operation failed")
