from beanly.modules.finance.domain.entities import (
    CashAccount,
    CashEntry,
    CashMovement,
    Expense,
    ExpenseCategory,
    FinanceEntry,
)
from beanly.modules.finance.domain.enums import (
    CashAccountType,
    CashFlowActivity,
    CashMovementType,
    ExpenseStatus,
    FinanceEntryType,
)
from beanly.modules.finance.infrastructure.db.models import (
    CashAccountModel,
    CashEntryModel,
    CashMovementModel,
    ExpenseCategoryModel,
    ExpenseModel,
    FinanceEntryModel,
)


def finance_entry(model: FinanceEntryModel) -> FinanceEntry:
    return FinanceEntry(
        model.id,
        model.organization_id,
        model.location_id,
        FinanceEntryType(model.entry_type),
        model.amount,
        model.currency_code,
        model.effective_at,
        model.description,
        model.expense_category_id,
        model.source_type,
        model.source_id,
        model.source_event_id,
        model.entry_role,
        model.reversal_of_id,
        model.quality_status,
        model.created_at,
    )


def cash_entry(model: CashEntryModel) -> CashEntry:
    return CashEntry(
        model.id,
        model.organization_id,
        model.location_id,
        model.cash_account_id,
        model.amount_minor,
        model.currency_code,
        CashFlowActivity(model.cash_flow_activity),
        model.effective_at,
        model.description,
        model.source_type,
        model.source_id,
        model.source_event_id,
        model.entry_role,
        model.reversal_of_id,
        model.created_at,
    )


def category(model: ExpenseCategoryModel) -> ExpenseCategory:
    return ExpenseCategory(
        model.id,
        model.organization_id,
        model.name,
        model.sort_order,
        model.is_active,
        model.created_at,
        model.updated_at,
    )


def account(model: CashAccountModel, balance_minor: int = 0) -> CashAccount:
    return CashAccount(
        model.id,
        model.organization_id,
        model.location_id,
        model.name,
        CashAccountType(model.type),
        model.currency_code,
        model.system_key,
        model.opening_balance_minor,
        model.is_active,
        model.created_at,
        model.updated_at,
        balance_minor,
    )


def expense(model: ExpenseModel) -> Expense:
    return Expense(
        model.id,
        model.organization_id,
        model.location_id,
        model.number,
        model.category_id,
        ExpenseStatus(model.status),
        model.amount_minor,
        model.currency_code,
        model.cash_account_id,
        model.vendor,
        model.occurred_at,
        model.description,
        model.created_by,
        model.posted_by,
        model.posted_at,
        model.reversed_by,
        model.reversed_at,
        model.finance_entry_id,
        model.cash_entry_id,
        model.created_at,
        model.updated_at,
    )


def cash_movement(model: CashMovementModel) -> CashMovement:
    return CashMovement(
        model.id,
        model.organization_id,
        model.location_id,
        CashMovementType(model.type),
        model.amount_minor,
        model.currency_code,
        model.from_account_id,
        model.to_account_id,
        CashFlowActivity(model.cash_flow_activity),
        model.occurred_at,
        model.description,
        model.created_by,
        model.reversed_by,
        model.reversed_at,
        model.out_entry_id,
        model.in_entry_id,
        model.created_at,
    )
