from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from beanly.modules.finance.domain.enums import (
    CashAccountType,
    CashFlowActivity,
    CashMovementType,
    ExpenseStatus,
    FinanceEntryType,
)

PositiveMinor = Annotated[str, Field(pattern=r"^[0-9]{1,19}$")]
SignedMinor = Annotated[str, Field(pattern=r"^-?[0-9]{1,19}$")]


class ExpenseCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    sort_order: int = Field(default=0, ge=0)


class ExpenseCategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    sort_order: int | None = Field(default=None, ge=0)


class ExpenseCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ExpenseRequest(BaseModel):
    location_id: UUID | None = None
    category_id: UUID
    amount_minor: PositiveMinor
    cash_account_id: UUID | None = None
    vendor: str | None = Field(default=None, max_length=200)
    occurred_at: datetime
    description: str | None = Field(default=None, max_length=4000)


class ExpensePatch(BaseModel):
    location_id: UUID | None = None
    category_id: UUID | None = None
    amount_minor: PositiveMinor | None = None
    cash_account_id: UUID | None = None
    vendor: str | None = Field(default=None, max_length=200)
    occurred_at: datetime | None = None
    description: str | None = Field(default=None, max_length=4000)


class ExpenseResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    number: str
    category_id: UUID
    status: ExpenseStatus
    amount_minor: str
    currency_code: str
    cash_account_id: UUID | None
    vendor: str | None
    occurred_at: datetime
    description: str | None
    created_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    finance_entry_id: UUID | None
    cash_entry_id: UUID | None
    created_at: datetime
    updated_at: datetime


class CashAccountRequest(BaseModel):
    location_id: UUID | None = None
    name: str = Field(min_length=1, max_length=150)
    type: CashAccountType
    opening_balance_minor: SignedMinor = "0"


class CashAccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: CashAccountType | None = None


class CashAccountResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    name: str
    type: CashAccountType
    currency_code: str
    system_key: str | None
    opening_balance_minor: str
    balance_minor: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CashMovementRequest(BaseModel):
    location_id: UUID | None = None
    type: CashMovementType
    amount_minor: PositiveMinor
    from_account_id: UUID | None = None
    to_account_id: UUID | None = None
    cash_flow_activity: CashFlowActivity | None = None
    occurred_at: datetime
    description: str | None = Field(default=None, max_length=255)


class CashMovementResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    type: CashMovementType
    amount_minor: str
    currency_code: str
    from_account_id: UUID | None
    to_account_id: UUID | None
    cash_flow_activity: CashFlowActivity
    occurred_at: datetime
    description: str | None
    created_by: UUID
    reversed_by: UUID | None
    reversed_at: datetime | None
    out_entry_id: UUID | None
    in_entry_id: UUID | None
    created_at: datetime


class DataQualityResponse(BaseModel):
    cogs_complete: bool
    incomplete_cogs_sales: int


class PnlResponse(BaseModel):
    currency_code: str
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    inventory_losses: Decimal
    inventory_gains: Decimal
    operating_expenses: Decimal
    other_income: Decimal
    other_expenses: Decimal
    operating_profit: Decimal
    gross_margin_percent: Decimal | None
    data_quality: DataQualityResponse


class ExpenseBreakdownRow(BaseModel):
    category_id: UUID | None
    name: str
    amount: Decimal


class PnlBreakdownResponse(BaseModel):
    currency_code: str
    operating_expenses: list[ExpenseBreakdownRow]


class LocationPnlResponse(BaseModel):
    location_id: UUID | None
    location_name: str
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    operating_profit: Decimal


class CashFlowSectionResponse(BaseModel):
    inflows_minor: str
    outflows_minor: str
    net_minor: str


class CashFlowResponse(BaseModel):
    currency_code: str
    opening_cash_minor: str
    operating: CashFlowSectionResponse
    investing: CashFlowSectionResponse
    financing: CashFlowSectionResponse
    net_cash_movement_minor: str
    closing_cash_minor: str


class FinanceEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    entry_type: FinanceEntryType
    amount: Decimal
    currency_code: str
    effective_at: datetime
    description: str | None
    expense_category_id: UUID | None
    source_type: str
    source_id: UUID | None
    source_event_id: UUID | None
    entry_role: str
    reversal_of_id: UUID | None
    quality_status: str | None
    created_at: datetime
