from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.finance.domain.entities import (
    CashAccount,
    CashEntry,
    CashMovement,
    Expense,
    ExpenseCategory,
    FinanceEntry,
)
from beanly.modules.finance.domain.enums import FinanceEntryType
from beanly.modules.finance.infrastructure.db import mappers
from beanly.modules.finance.infrastructure.db.models import (
    CashAccountModel,
    CashEntryModel,
    CashMovementModel,
    ExpenseCategoryModel,
    ExpenseModel,
    FinanceEntryModel,
)
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    OrganizationModel,
)


class SqlAlchemyFinanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def currency(self, organization_id: UUID) -> str:
        value = await self.session.scalar(
            select(OrganizationModel.currency_code).where(
                OrganizationModel.id == organization_id
            )
        )
        if value is None:
            raise ValueError("Organization not found")
        return value

    async def location_exists(self, organization_id: UUID, location_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(LocationModel.id).where(
                    LocationModel.organization_id == organization_id,
                    LocationModel.id == location_id,
                )
            )
            is not None
        )

    async def add_finance_entry(self, value: FinanceEntry) -> bool:
        model = FinanceEntryModel(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            entry_type=value.entry_type.value,
            amount=value.amount,
            currency_code=value.currency_code,
            effective_at=value.effective_at,
            description=value.description,
            expense_category_id=value.expense_category_id,
            source_type=value.source_type,
            source_id=value.source_id,
            source_event_id=value.source_event_id,
            entry_role=value.entry_role,
            reversal_of_id=value.reversal_of_id,
            quality_status=value.quality_status,
            created_at=value.created_at,
        )
        return await self._insert_once(model)

    async def add_cash_entry(self, value: CashEntry) -> bool:
        model = CashEntryModel(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            cash_account_id=value.cash_account_id,
            amount_minor=value.amount_minor,
            currency_code=value.currency_code,
            cash_flow_activity=value.cash_flow_activity.value,
            effective_at=value.effective_at,
            description=value.description,
            source_type=value.source_type,
            source_id=value.source_id,
            source_event_id=value.source_event_id,
            entry_role=value.entry_role,
            reversal_of_id=value.reversal_of_id,
            created_at=value.created_at,
        )
        return await self._insert_once(model)

    async def _insert_once(self, model) -> bool:
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
            return True
        except IntegrityError:
            if isinstance(model, (FinanceEntryModel, CashEntryModel)):
                duplicate = await self.session.scalar(
                    select(type(model).id).where(
                        type(model).organization_id == model.organization_id,
                        type(model).source_type == model.source_type,
                        type(model).source_id == model.source_id,
                        type(model).entry_role == model.entry_role,
                    )
                )
            elif isinstance(model, CashAccountModel) and model.system_key is not None:
                duplicate = await self.session.scalar(
                    select(CashAccountModel.id).where(
                        CashAccountModel.organization_id == model.organization_id,
                        CashAccountModel.location_id == model.location_id,
                        CashAccountModel.system_key == model.system_key,
                    )
                )
            else:
                raise
            if duplicate is None:
                raise
            return False

    async def find_finance_entry(
        self, organization_id: UUID, source_type: str, source_id: UUID, entry_role: str
    ) -> FinanceEntry | None:
        model = await self.session.scalar(
            select(FinanceEntryModel).where(
                FinanceEntryModel.organization_id == organization_id,
                FinanceEntryModel.source_type == source_type,
                FinanceEntryModel.source_id == source_id,
                FinanceEntryModel.entry_role == entry_role,
            )
        )
        return mappers.finance_entry(model) if model else None

    async def find_cash_entry(
        self, organization_id: UUID, source_type: str, source_id: UUID, entry_role: str
    ) -> CashEntry | None:
        model = await self.session.scalar(
            select(CashEntryModel).where(
                CashEntryModel.organization_id == organization_id,
                CashEntryModel.source_type == source_type,
                CashEntryModel.source_id == source_id,
                CashEntryModel.entry_role == entry_role,
            )
        )
        return mappers.cash_entry(model) if model else None

    async def system_account(
        self,
        organization_id: UUID,
        location_id: UUID,
        method: str,
        currency_code: str,
    ) -> CashAccount:
        key = f"PAYMENT:{method}"
        existing = await self.session.scalar(
            select(CashAccountModel).where(
                CashAccountModel.organization_id == organization_id,
                CashAccountModel.location_id == location_id,
                CashAccountModel.system_key == key,
            )
        )
        if existing:
            return mappers.account(existing)
        types = {"CASH": "CASH", "CARD": "CARD_CLEARING", "OTHER": "OTHER"}
        names = {"CASH": "Cash", "CARD": "Card", "OTHER": "Other"}
        location_name = await self.session.scalar(
            select(LocationModel.name).where(
                LocationModel.organization_id == organization_id,
                LocationModel.id == location_id,
            )
        )
        if location_name is None:
            raise ValueError("Payment location not found")
        candidate = CashAccountModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            name=f"{names[method]} — {location_name}",
            type=types[method],
            currency_code=currency_code,
            system_key=key,
            opening_balance_minor=0,
            is_active=True,
        )
        await self._insert_once(candidate)
        model = await self.session.scalar(
            select(CashAccountModel).where(
                CashAccountModel.organization_id == organization_id,
                CashAccountModel.location_id == location_id,
                CashAccountModel.system_key == key,
            )
        )
        if model is None:
            raise RuntimeError("Could not create payment cash account")
        return mappers.account(model)

    async def add_category(self, value: ExpenseCategory) -> None:
        self.session.add(
            ExpenseCategoryModel(
                id=value.id,
                organization_id=value.organization_id,
                name=value.name,
                sort_order=value.sort_order,
                is_active=value.is_active,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
        )
        await self.session.flush()

    async def list_categories(self, organization_id: UUID) -> list[ExpenseCategory]:
        values = await self.session.scalars(
            select(ExpenseCategoryModel)
            .where(ExpenseCategoryModel.organization_id == organization_id)
            .order_by(ExpenseCategoryModel.sort_order, ExpenseCategoryModel.name)
        )
        return [mappers.category(value) for value in values]

    async def get_category(
        self, organization_id: UUID, category_id: UUID, *, lock: bool = False
    ) -> ExpenseCategory | None:
        statement = select(ExpenseCategoryModel).where(
            ExpenseCategoryModel.organization_id == organization_id,
            ExpenseCategoryModel.id == category_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return mappers.category(model) if model else None

    async def update_category(self, value: ExpenseCategory) -> None:
        model = await self.session.scalar(
            select(ExpenseCategoryModel).where(
                ExpenseCategoryModel.organization_id == value.organization_id,
                ExpenseCategoryModel.id == value.id,
            )
        )
        if model is None:
            raise ValueError("Expense category not found")
        model.name = value.name
        model.sort_order = value.sort_order
        model.is_active = value.is_active
        model.updated_at = value.updated_at
        await self.session.flush()

    async def add_account(self, value: CashAccount) -> None:
        self.session.add(
            CashAccountModel(
                id=value.id,
                organization_id=value.organization_id,
                location_id=value.location_id,
                name=value.name,
                type=value.type.value,
                currency_code=value.currency_code,
                system_key=value.system_key,
                opening_balance_minor=value.opening_balance_minor,
                is_active=value.is_active,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
        )
        await self.session.flush()

    async def list_accounts(self, organization_id: UUID) -> list[CashAccount]:
        rows = await self.session.execute(
            select(CashAccountModel, func.coalesce(func.sum(CashEntryModel.amount_minor), 0))
            .outerjoin(CashEntryModel, CashEntryModel.cash_account_id == CashAccountModel.id)
            .where(CashAccountModel.organization_id == organization_id)
            .group_by(CashAccountModel.id)
            .order_by(CashAccountModel.name, CashAccountModel.id)
        )
        return [
            mappers.account(model, model.opening_balance_minor + int(movement))
            for model, movement in rows
        ]

    async def get_account(
        self, organization_id: UUID, account_id: UUID, *, lock: bool = False
    ) -> CashAccount | None:
        statement = select(CashAccountModel).where(
            CashAccountModel.organization_id == organization_id,
            CashAccountModel.id == account_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return mappers.account(model) if model else None

    async def update_account(self, value: CashAccount) -> None:
        model = await self.session.scalar(
            select(CashAccountModel).where(
                CashAccountModel.organization_id == value.organization_id,
                CashAccountModel.id == value.id,
            )
        )
        if model is None:
            raise ValueError("Cash account not found")
        model.name = value.name
        model.type = value.type.value
        model.is_active = value.is_active
        model.updated_at = value.updated_at
        await self.session.flush()

    async def add_expense(self, value: Expense) -> None:
        self.session.add(self._expense_model(value))
        await self.session.flush()

    async def list_expenses(self, organization_id: UUID) -> list[Expense]:
        values = await self.session.scalars(
            select(ExpenseModel)
            .where(ExpenseModel.organization_id == organization_id)
            .order_by(ExpenseModel.occurred_at.desc(), ExpenseModel.id.desc())
        )
        return [mappers.expense(value) for value in values]

    async def get_expense(
        self, organization_id: UUID, expense_id: UUID, *, lock: bool = False
    ) -> Expense | None:
        statement = select(ExpenseModel).where(
            ExpenseModel.organization_id == organization_id,
            ExpenseModel.id == expense_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return mappers.expense(model) if model else None

    async def update_expense(self, value: Expense) -> None:
        model = await self.session.scalar(
            select(ExpenseModel).where(
                ExpenseModel.organization_id == value.organization_id,
                ExpenseModel.id == value.id,
            )
        )
        if model is None:
            raise ValueError("Expense not found")
        for field in (
            "location_id",
            "category_id",
            "amount_minor",
            "currency_code",
            "cash_account_id",
            "vendor",
            "occurred_at",
            "description",
            "posted_by",
            "posted_at",
            "reversed_by",
            "reversed_at",
            "finance_entry_id",
            "cash_entry_id",
            "updated_at",
        ):
            setattr(model, field, getattr(value, field))
        model.status = value.status.value
        await self.session.flush()

    async def add_cash_movement(self, value: CashMovement) -> None:
        self.session.add(self._cash_movement_model(value))
        await self.session.flush()

    async def list_cash_movements(self, organization_id: UUID) -> list[CashMovement]:
        values = await self.session.scalars(
            select(CashMovementModel)
            .where(CashMovementModel.organization_id == organization_id)
            .order_by(CashMovementModel.occurred_at.desc(), CashMovementModel.id.desc())
        )
        return [mappers.cash_movement(value) for value in values]

    async def get_cash_movement(
        self, organization_id: UUID, movement_id: UUID, *, lock: bool = False
    ) -> CashMovement | None:
        statement = select(CashMovementModel).where(
            CashMovementModel.organization_id == organization_id,
            CashMovementModel.id == movement_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return mappers.cash_movement(model) if model else None

    async def update_cash_movement(self, value: CashMovement) -> None:
        model = await self.session.scalar(
            select(CashMovementModel).where(
                CashMovementModel.organization_id == value.organization_id,
                CashMovementModel.id == value.id,
            )
        )
        if model is None:
            raise ValueError("Cash movement not found")
        model.reversed_by = value.reversed_by
        model.reversed_at = value.reversed_at
        model.out_entry_id = value.out_entry_id
        model.in_entry_id = value.in_entry_id
        await self.session.flush()

    async def list_finance_entries(
        self,
        organization_id: UUID,
        date_from: datetime | None,
        date_to: datetime | None,
        location_id: UUID | None,
        entry_type: FinanceEntryType | None,
        source_type: str | None,
        source_id: UUID | None,
    ) -> list[FinanceEntry]:
        statement = select(FinanceEntryModel).where(
            FinanceEntryModel.organization_id == organization_id
        )
        filters = (
            (FinanceEntryModel.effective_at >= date_from) if date_from else None,
            (FinanceEntryModel.effective_at < date_to) if date_to else None,
            (FinanceEntryModel.location_id == location_id) if location_id else None,
            (FinanceEntryModel.entry_type == entry_type.value) if entry_type else None,
            (FinanceEntryModel.source_type == source_type) if source_type else None,
            (FinanceEntryModel.source_id == source_id) if source_id else None,
        )
        statement = statement.where(*(value for value in filters if value is not None))
        values = await self.session.scalars(
            statement.order_by(FinanceEntryModel.effective_at.desc(), FinanceEntryModel.id.desc())
        )
        return [mappers.finance_entry(value) for value in values]

    async def finance_totals(
        self,
        organization_id: UUID,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> dict[str, Decimal]:
        statement = (
            select(FinanceEntryModel.entry_type, func.sum(FinanceEntryModel.amount))
            .where(
                FinanceEntryModel.organization_id == organization_id,
                FinanceEntryModel.effective_at >= date_from,
                FinanceEntryModel.effective_at < date_to,
            )
            .group_by(FinanceEntryModel.entry_type)
        )
        if location_id is not None:
            statement = statement.where(FinanceEntryModel.location_id == location_id)
        return {key: value for key, value in await self.session.execute(statement)}

    async def incomplete_cogs_count(
        self,
        organization_id: UUID,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> int:
        statement = select(func.count(FinanceEntryModel.id)).where(
            FinanceEntryModel.organization_id == organization_id,
            FinanceEntryModel.entry_type == FinanceEntryType.COGS.value,
            FinanceEntryModel.quality_status.in_(("INCOMPLETE", "ESTIMATED")),
            FinanceEntryModel.effective_at >= date_from,
            FinanceEntryModel.effective_at < date_to,
        )
        if location_id is not None:
            statement = statement.where(FinanceEntryModel.location_id == location_id)
        return int(await self.session.scalar(statement) or 0)

    async def expense_breakdown(
        self,
        organization_id: UUID,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> list[tuple[UUID | None, str, Decimal]]:
        statement = (
            select(
                FinanceEntryModel.expense_category_id,
                ExpenseCategoryModel.name,
                func.sum(FinanceEntryModel.amount),
            )
            .join(
                ExpenseCategoryModel,
                ExpenseCategoryModel.id == FinanceEntryModel.expense_category_id,
            )
            .where(
                FinanceEntryModel.organization_id == organization_id,
                FinanceEntryModel.entry_type == FinanceEntryType.OPERATING_EXPENSE.value,
                FinanceEntryModel.effective_at >= date_from,
                FinanceEntryModel.effective_at < date_to,
            )
            .group_by(FinanceEntryModel.expense_category_id, ExpenseCategoryModel.name)
            .order_by(ExpenseCategoryModel.name)
        )
        if location_id is not None:
            statement = statement.where(FinanceEntryModel.location_id == location_id)
        return list(await self.session.execute(statement))

    async def location_totals(
        self, organization_id: UUID, date_from: datetime, date_to: datetime
    ) -> list[tuple[UUID | None, str, dict[str, Decimal]]]:
        rows = await self.session.execute(
            select(
                FinanceEntryModel.location_id,
                func.coalesce(LocationModel.name, "Central / Unallocated"),
                FinanceEntryModel.entry_type,
                func.sum(FinanceEntryModel.amount),
            )
            .outerjoin(LocationModel, LocationModel.id == FinanceEntryModel.location_id)
            .where(
                FinanceEntryModel.organization_id == organization_id,
                FinanceEntryModel.effective_at >= date_from,
                FinanceEntryModel.effective_at < date_to,
            )
            .group_by(
                FinanceEntryModel.location_id,
                LocationModel.name,
                FinanceEntryModel.entry_type,
            )
        )
        grouped: dict[tuple[UUID | None, str], dict[str, Decimal]] = {}
        for location_id, name, entry_type, amount in rows:
            grouped.setdefault((location_id, name), {})[entry_type] = amount
        return [(key[0], key[1], totals) for key, totals in grouped.items()]

    async def cash_totals(
        self,
        organization_id: UUID,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> tuple[int, dict[str, tuple[int, int]]]:
        account_filter = [CashAccountModel.organization_id == organization_id]
        entry_filter = [CashEntryModel.organization_id == organization_id]
        if location_id is not None:
            account_filter.append(CashAccountModel.location_id == location_id)
            entry_filter.append(CashEntryModel.location_id == location_id)
        opening_accounts = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(CashAccountModel.opening_balance_minor), 0)).where(
                    *account_filter
                )
            )
            or 0
        )
        previous = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(CashEntryModel.amount_minor), 0)).where(
                    *entry_filter, CashEntryModel.effective_at < date_from
                )
            )
            or 0
        )
        rows = await self.session.execute(
            select(
                CashEntryModel.cash_flow_activity,
                func.sum(
                    case(
                        (CashEntryModel.amount_minor > 0, CashEntryModel.amount_minor),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (CashEntryModel.amount_minor < 0, -CashEntryModel.amount_minor),
                        else_=0,
                    )
                ),
            )
            .where(
                *entry_filter,
                CashEntryModel.effective_at >= date_from,
                CashEntryModel.effective_at < date_to,
            )
            .group_by(CashEntryModel.cash_flow_activity)
        )
        return opening_accounts + previous, {
            key: (int(inflows), int(outflows)) for key, inflows, outflows in rows
        }

    async def data_as_of(
        self, organization_id: UUID, location_id: UUID | None
    ) -> datetime | None:
        statement = select(func.max(FinanceEntryModel.created_at)).where(
            FinanceEntryModel.organization_id == organization_id
        )
        if location_id is not None:
            statement = statement.where(FinanceEntryModel.location_id == location_id)
        return await self.session.scalar(statement)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    @staticmethod
    def _expense_model(value: Expense) -> ExpenseModel:
        return ExpenseModel(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            number=value.number,
            category_id=value.category_id,
            status=value.status.value,
            amount_minor=value.amount_minor,
            currency_code=value.currency_code,
            cash_account_id=value.cash_account_id,
            vendor=value.vendor,
            occurred_at=value.occurred_at,
            description=value.description,
            created_by=value.created_by,
            posted_by=value.posted_by,
            posted_at=value.posted_at,
            reversed_by=value.reversed_by,
            reversed_at=value.reversed_at,
            finance_entry_id=value.finance_entry_id,
            cash_entry_id=value.cash_entry_id,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )

    @staticmethod
    def _cash_movement_model(value: CashMovement) -> CashMovementModel:
        return CashMovementModel(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            type=value.type.value,
            amount_minor=value.amount_minor,
            currency_code=value.currency_code,
            from_account_id=value.from_account_id,
            to_account_id=value.to_account_id,
            cash_flow_activity=value.cash_flow_activity.value,
            occurred_at=value.occurred_at,
            description=value.description,
            created_by=value.created_by,
            reversed_by=value.reversed_by,
            reversed_at=value.reversed_at,
            out_entry_id=value.out_entry_id,
            in_entry_id=value.in_entry_id,
            created_at=value.created_at,
        )
