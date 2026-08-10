from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.finance.application.access import allowed_locations, ensure_location
from beanly.modules.finance.domain.entities import (
    CashEntry,
    Expense,
    ExpenseCategory,
    FinanceEntry,
)
from beanly.modules.finance.domain.enums import (
    CashFlowActivity,
    ExpenseStatus,
    FinanceEntryType,
)
from beanly.modules.finance.domain.events import ExpenseCreated, ExpensePosted, ExpenseReversed
from beanly.modules.finance.domain.exceptions import FinanceNotFound, InvalidFinanceOperation
from beanly.modules.finance.domain.repositories import FinanceRepository
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext


class ExpenseService:
    def __init__(
        self,
        repository: FinanceRepository,
        sink: DomainEventSink,
        organizations: OrganizationService,
    ) -> None:
        self.repository = repository
        self.sink = sink
        self.organizations = organizations

    async def list_categories(self, context: TenantContext) -> list[ExpenseCategory]:
        return await self.repository.list_categories(context.organization_id)

    async def create_category(
        self, context: TenantContext, name: str, sort_order: int
    ) -> ExpenseCategory:
        if sort_order < 0:
            raise InvalidFinanceOperation("sort_order must be nonnegative")
        now = datetime.now(UTC)
        value = ExpenseCategory(
            uuid4(),
            context.organization_id,
            _required_name(name),
            sort_order,
            True,
            now,
            now,
        )
        try:
            await self.repository.add_category(value)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return value

    async def update_category(
        self,
        context: TenantContext,
        category_id: UUID,
        name: str,
        sort_order: int,
    ) -> ExpenseCategory:
        if sort_order < 0:
            raise InvalidFinanceOperation("sort_order must be nonnegative")
        try:
            current = await self.repository.get_category(
                context.organization_id, category_id, lock=True
            )
            if current is None:
                raise FinanceNotFound("Expense category not found")
            value = replace(
                current,
                name=_required_name(name),
                sort_order=sort_order,
                updated_at=datetime.now(UTC),
            )
            await self.repository.update_category(value)
            await self.repository.commit()
            return value
        except Exception:
            await self.repository.rollback()
            raise

    async def deactivate_category(
        self, context: TenantContext, category_id: UUID
    ) -> ExpenseCategory:
        try:
            current = await self.repository.get_category(
                context.organization_id, category_id, lock=True
            )
            if current is None:
                raise FinanceNotFound("Expense category not found")
            value = replace(current, is_active=False, updated_at=datetime.now(UTC))
            await self.repository.update_category(value)
            await self.repository.commit()
            return value
        except Exception:
            await self.repository.rollback()
            raise

    async def create(
        self,
        context: TenantContext,
        category_id: UUID,
        amount_minor: int,
        occurred_at: datetime,
        location_id: UUID | None,
        cash_account_id: UUID | None,
        vendor: str | None,
        description: str | None,
    ) -> Expense:
        await self._validate(
            context,
            category_id,
            amount_minor,
            location_id,
            cash_account_id,
        )
        now = datetime.now(UTC)
        value = Expense(
            uuid4(),
            context.organization_id,
            location_id,
            f"EXP-{uuid4().hex[:12].upper()}",
            category_id,
            ExpenseStatus.DRAFT,
            amount_minor,
            await self.repository.currency(context.organization_id),
            cash_account_id,
            _text(vendor, 200),
            _aware(occurred_at),
            _text(description, 4000),
            context.user_id,
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
        )
        try:
            await self.repository.add_expense(value)
            await self.sink.stage(ExpenseCreated(context.organization_id, value.id))
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return value

    async def list(self, context: TenantContext) -> list[Expense]:
        values = await self.repository.list_expenses(context.organization_id)
        allowed = await allowed_locations(self.organizations, context)
        return (
            values
            if allowed is None
            else [value for value in values if value.location_id in allowed]
        )

    async def get(self, context: TenantContext, expense_id: UUID) -> Expense:
        value = await self.repository.get_expense(context.organization_id, expense_id)
        if value is None:
            raise FinanceNotFound("Expense not found")
        await self._ensure_visible(context, value)
        return value

    async def update(
        self,
        context: TenantContext,
        expense_id: UUID,
        category_id: UUID,
        amount_minor: int,
        occurred_at: datetime,
        location_id: UUID | None,
        cash_account_id: UUID | None,
        vendor: str | None,
        description: str | None,
    ) -> Expense:
        try:
            current = await self.repository.get_expense(
                context.organization_id, expense_id, lock=True
            )
            if current is None:
                raise FinanceNotFound("Expense not found")
            await self._ensure_visible(context, current)
            if current.status != ExpenseStatus.DRAFT:
                raise InvalidFinanceOperation("Posted expenses are immutable")
            await self._validate(
                context,
                category_id,
                amount_minor,
                location_id,
                cash_account_id,
            )
            value = replace(
                current,
                category_id=category_id,
                amount_minor=amount_minor,
                occurred_at=_aware(occurred_at),
                location_id=location_id,
                cash_account_id=cash_account_id,
                vendor=_text(vendor, 200),
                description=_text(description, 4000),
                updated_at=datetime.now(UTC),
            )
            await self.repository.update_expense(value)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return value

    async def post(self, context: TenantContext, expense_id: UUID) -> Expense:
        try:
            value = await self.repository.get_expense(
                context.organization_id, expense_id, lock=True
            )
            if value is None:
                raise FinanceNotFound("Expense not found")
            await self._ensure_visible(context, value)
            if value.status == ExpenseStatus.POSTED:
                await self.repository.rollback()
                return value
            if value.status != ExpenseStatus.DRAFT:
                raise InvalidFinanceOperation("Only draft expenses can be posted")
            await self._validate(
                context,
                value.category_id,
                value.amount_minor,
                value.location_id,
                value.cash_account_id,
            )
            now = datetime.now(UTC)
            finance = FinanceEntry(
                uuid4(),
                value.organization_id,
                value.location_id,
                FinanceEntryType.OPERATING_EXPENSE,
                -(Decimal(value.amount_minor) / 100),
                value.currency_code,
                value.occurred_at,
                value.description or value.vendor or "Operating expense",
                value.category_id,
                "EXPENSE",
                value.id,
                None,
                "OPERATING_EXPENSE",
                None,
                None,
                now,
            )
            await self.repository.add_finance_entry(finance)
            cash: CashEntry | None = None
            if value.cash_account_id is not None:
                account = await self._account(value.organization_id, value.cash_account_id)
                cash = CashEntry(
                    uuid4(),
                    value.organization_id,
                    account.location_id,
                    account.id,
                    -value.amount_minor,
                    value.currency_code,
                    CashFlowActivity.OPERATING,
                    value.occurred_at,
                    value.description or value.vendor or "Expense payment",
                    "EXPENSE",
                    value.id,
                    None,
                    "EXPENSE_PAYMENT",
                    None,
                    now,
                )
                await self.repository.add_cash_entry(cash)
            posted = replace(
                value,
                status=ExpenseStatus.POSTED,
                posted_by=context.user_id,
                posted_at=now,
                finance_entry_id=finance.id,
                cash_entry_id=cash.id if cash else None,
                updated_at=now,
            )
            await self.repository.update_expense(posted)
            await self.sink.stage(ExpensePosted(value.organization_id, value.id))
            await self.repository.commit()
            return posted
        except Exception:
            await self.repository.rollback()
            raise

    async def reverse(self, context: TenantContext, expense_id: UUID) -> Expense:
        try:
            value = await self.repository.get_expense(
                context.organization_id, expense_id, lock=True
            )
            if value is None:
                raise FinanceNotFound("Expense not found")
            await self._ensure_visible(context, value)
            if value.status == ExpenseStatus.REVERSED:
                await self.repository.rollback()
                return value
            if value.status != ExpenseStatus.POSTED:
                raise InvalidFinanceOperation("Only posted expenses can be reversed")
            original = await self.repository.find_finance_entry(
                value.organization_id, "EXPENSE", value.id, "OPERATING_EXPENSE"
            )
            if original is None:
                raise FinanceNotFound("Expense finance entry not found")
            now = datetime.now(UTC)
            await self.repository.add_finance_entry(
                replace(
                    original,
                    id=uuid4(),
                    amount=-original.amount,
                    effective_at=now,
                    description="Expense reversal",
                    source_type="EXPENSE_REVERSAL",
                    source_event_id=None,
                    entry_role="OPERATING_EXPENSE_REVERSAL",
                    reversal_of_id=original.id,
                    created_at=now,
                )
            )
            if value.cash_entry_id is not None:
                cash = await self.repository.find_cash_entry(
                    value.organization_id, "EXPENSE", value.id, "EXPENSE_PAYMENT"
                )
                if cash is None:
                    raise FinanceNotFound("Expense cash entry not found")
                await self.repository.add_cash_entry(
                    replace(
                        cash,
                        id=uuid4(),
                        amount_minor=-cash.amount_minor,
                        effective_at=now,
                        description="Expense payment reversal",
                        source_type="EXPENSE_REVERSAL",
                        source_event_id=None,
                        entry_role="EXPENSE_PAYMENT_REVERSAL",
                        reversal_of_id=cash.id,
                        created_at=now,
                    )
                )
            reversed_value = replace(
                value,
                status=ExpenseStatus.REVERSED,
                reversed_by=context.user_id,
                reversed_at=now,
                updated_at=now,
            )
            await self.repository.update_expense(reversed_value)
            await self.sink.stage(ExpenseReversed(value.organization_id, value.id))
            await self.repository.commit()
            return reversed_value
        except Exception:
            await self.repository.rollback()
            raise

    async def _validate(
        self,
        context: TenantContext,
        category_id: UUID,
        amount_minor: int,
        location_id: UUID | None,
        cash_account_id: UUID | None,
    ) -> None:
        organization_id = context.organization_id
        if location_id is None and await allowed_locations(self.organizations, context) is not None:
            raise InvalidFinanceOperation(
                "location_id is required for restricted finance access"
            )
        if not 0 < amount_minor <= MAX_NUMERIC_20_6_MINOR:
            raise InvalidFinanceOperation("Amount exceeds FinanceEntry NUMERIC(20,6)")
        category = await self.repository.get_category(organization_id, category_id)
        if category is None or not category.is_active:
            raise InvalidFinanceOperation("Active expense category is required")
        if location_id is not None and not await self.repository.location_exists(
            organization_id, location_id
        ):
            raise InvalidFinanceOperation("Location not found")
        if location_id is not None:
            await ensure_location(self.organizations, context, location_id)
        if cash_account_id is not None:
            account = await self._account(organization_id, cash_account_id)
            if account.location_id is not None:
                await ensure_location(self.organizations, context, account.location_id)
            elif await allowed_locations(self.organizations, context) is not None:
                raise InvalidFinanceOperation("Cash account not found")
            if not account.is_active:
                raise InvalidFinanceOperation("Active cash account is required")
            if location_id is not None and account.location_id not in (None, location_id):
                raise InvalidFinanceOperation("Cash account belongs to another location")
            if account.currency_code != await self.repository.currency(organization_id):
                raise InvalidFinanceOperation("Cash account currency mismatch")

    async def _account(self, organization_id: UUID, account_id: UUID):
        value = await self.repository.get_account(organization_id, account_id)
        if value is None:
            raise InvalidFinanceOperation("Cash account not found")
        return value

    async def _ensure_visible(self, context: TenantContext, value: Expense) -> None:
        if value.location_id is not None:
            await ensure_location(self.organizations, context, value.location_id)
        elif await allowed_locations(self.organizations, context) is not None:
            raise FinanceNotFound("Expense not found")


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if len(result) > limit:
        raise InvalidFinanceOperation(f"Text must be at most {limit} characters")
    return result or None


def _required_name(value: str) -> str:
    result = value.strip()
    if not result or len(result) > 150:
        raise InvalidFinanceOperation("Name must contain between 1 and 150 characters")
    return result


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise InvalidFinanceOperation("Timestamp must include a timezone")
    return value.astimezone(UTC)
