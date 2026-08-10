from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.finance.domain.enums import (
    CashAccountType,
    CashFlowActivity,
    CashMovementType,
    ExpenseStatus,
    FinanceEntryType,
)


@dataclass(frozen=True, slots=True)
class FinanceEntry:
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


@dataclass(frozen=True, slots=True)
class CashEntry:
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    cash_account_id: UUID
    amount_minor: int
    currency_code: str
    cash_flow_activity: CashFlowActivity
    effective_at: datetime
    description: str | None
    source_type: str
    source_id: UUID | None
    source_event_id: UUID | None
    entry_role: str
    reversal_of_id: UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExpenseCategory:
    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CashAccount:
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    name: str
    type: CashAccountType
    currency_code: str
    system_key: str | None
    opening_balance_minor: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    balance_minor: int = 0


@dataclass(frozen=True, slots=True)
class Expense:
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    number: str
    category_id: UUID
    status: ExpenseStatus
    amount_minor: int
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


@dataclass(frozen=True, slots=True)
class CashMovement:
    id: UUID
    organization_id: UUID
    location_id: UUID | None
    type: CashMovementType
    amount_minor: int
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
