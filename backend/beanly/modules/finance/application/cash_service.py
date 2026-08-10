from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.core.money import MAX_BIGINT
from beanly.modules.finance.application.access import allowed_locations, ensure_location
from beanly.modules.finance.application.expense_service import _aware, _text
from beanly.modules.finance.domain.entities import CashAccount, CashEntry, CashMovement
from beanly.modules.finance.domain.enums import (
    CashAccountType,
    CashFlowActivity,
    CashMovementType,
)
from beanly.modules.finance.domain.events import CashMovementPosted, CashMovementReversed
from beanly.modules.finance.domain.exceptions import FinanceNotFound, InvalidFinanceOperation
from beanly.modules.finance.domain.repositories import FinanceRepository
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext


class CashService:
    def __init__(
        self,
        repository: FinanceRepository,
        sink: DomainEventSink,
        organizations: OrganizationService,
    ) -> None:
        self.repository = repository
        self.sink = sink
        self.organizations = organizations

    async def create_account(
        self,
        context: TenantContext,
        name: str,
        type_: CashAccountType,
        location_id: UUID | None,
        opening_balance_minor: int,
    ) -> CashAccount:
        if abs(opening_balance_minor) > MAX_BIGINT:
            raise InvalidFinanceOperation("Opening balance must fit BIGINT")
        if location_id is not None and not await self.repository.location_exists(
            context.organization_id, location_id
        ):
            raise InvalidFinanceOperation("Location not found")
        if location_id is not None:
            await ensure_location(self.organizations, context, location_id)
        elif await allowed_locations(self.organizations, context) is not None:
            raise InvalidFinanceOperation(
                "location_id is required for restricted finance access"
            )
        now = datetime.now(UTC)
        value = CashAccount(
            uuid4(),
            context.organization_id,
            location_id,
            _required_name(name),
            type_,
            await self.repository.currency(context.organization_id),
            None,
            opening_balance_minor,
            True,
            now,
            now,
            opening_balance_minor,
        )
        try:
            await self.repository.add_account(value)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return value

    async def list_accounts(self, context: TenantContext) -> list[CashAccount]:
        values = await self.repository.list_accounts(context.organization_id)
        allowed = await allowed_locations(self.organizations, context)
        return (
            values
            if allowed is None
            else [value for value in values if value.location_id in allowed]
        )

    async def update_account(
        self,
        context: TenantContext,
        account_id: UUID,
        name: str,
        type_: CashAccountType,
    ) -> CashAccount:
        try:
            value = await self.repository.get_account(
                context.organization_id, account_id, lock=True
            )
            if value is None:
                raise FinanceNotFound("Cash account not found")
            if value.location_id is not None:
                await ensure_location(self.organizations, context, value.location_id)
            elif await allowed_locations(self.organizations, context) is not None:
                raise FinanceNotFound("Cash account not found")
            if value.system_key is not None and type_ != value.type:
                raise InvalidFinanceOperation("System account type cannot change")
            updated = replace(
                value,
                name=_required_name(name),
                type=type_,
                updated_at=datetime.now(UTC),
            )
            await self.repository.update_account(updated)
            await self.repository.commit()
            return updated
        except Exception:
            await self.repository.rollback()
            raise

    async def deactivate_account(
        self, context: TenantContext, account_id: UUID
    ) -> CashAccount:
        try:
            value = await self.repository.get_account(
                context.organization_id, account_id, lock=True
            )
            if value is None:
                raise FinanceNotFound("Cash account not found")
            if value.location_id is not None:
                await ensure_location(self.organizations, context, value.location_id)
            elif await allowed_locations(self.organizations, context) is not None:
                raise FinanceNotFound("Cash account not found")
            if value.system_key is not None:
                raise InvalidFinanceOperation("System payment accounts cannot be deactivated")
            updated = replace(value, is_active=False, updated_at=datetime.now(UTC))
            await self.repository.update_account(updated)
            await self.repository.commit()
            return updated
        except Exception:
            await self.repository.rollback()
            raise

    async def list_movements(self, context: TenantContext) -> list[CashMovement]:
        values = await self.repository.list_cash_movements(context.organization_id)
        allowed = await allowed_locations(self.organizations, context)
        if allowed is None:
            return values
        visible_accounts = {value.id for value in await self.list_accounts(context)}
        return [
            value
            for value in values
            if (value.from_account_id is None or value.from_account_id in visible_accounts)
            and (value.to_account_id is None or value.to_account_id in visible_accounts)
        ]

    async def create_movement(
        self,
        context: TenantContext,
        type_: CashMovementType,
        amount_minor: int,
        occurred_at: datetime,
        from_account_id: UUID | None,
        to_account_id: UUID | None,
        activity: CashFlowActivity | None,
        description: str | None,
        location_id: UUID | None = None,
    ) -> CashMovement:
        if not 0 < amount_minor <= MAX_BIGINT:
            raise InvalidFinanceOperation("Amount must fit a positive BIGINT")
        _validate_shape(type_, from_account_id, to_account_id)
        derived_activity = _activity(type_, activity)
        accounts = {}
        for account_id in (from_account_id, to_account_id):
            if account_id is None:
                continue
            account = await self.repository.get_account(context.organization_id, account_id)
            if account is None or not account.is_active:
                raise InvalidFinanceOperation("Active cash account is required")
            if account.location_id is not None:
                await ensure_location(self.organizations, context, account.location_id)
            elif await allowed_locations(self.organizations, context) is not None:
                raise InvalidFinanceOperation("Cash account not found")
            accounts[account_id] = account
        currency = await self.repository.currency(context.organization_id)
        if any(value.currency_code != currency for value in accounts.values()):
            raise InvalidFinanceOperation("Cash account currency mismatch")
        now = datetime.now(UTC)
        movement_id = uuid4()
        effective_at = _aware(occurred_at)
        out_entry = (
            CashEntry(
                uuid4(),
                context.organization_id,
                accounts[from_account_id].location_id,
                from_account_id,
                -amount_minor,
                currency,
                derived_activity,
                effective_at,
                _text(description, 255),
                "CASH_MOVEMENT",
                movement_id,
                None,
                "OUT",
                None,
                now,
            )
            if from_account_id is not None
            else None
        )
        in_entry = (
            CashEntry(
                uuid4(),
                context.organization_id,
                accounts[to_account_id].location_id,
                to_account_id,
                amount_minor,
                currency,
                derived_activity,
                effective_at,
                _text(description, 255),
                "CASH_MOVEMENT",
                movement_id,
                None,
                "IN",
                None,
                now,
            )
            if to_account_id is not None
            else None
        )
        locations = {value.location_id for value in accounts.values()}
        derived_location_id = locations.pop() if len(locations) == 1 else None
        if location_id is not None and location_id != derived_location_id:
            raise InvalidFinanceOperation("Movement location must match its cash account")
        value = CashMovement(
            movement_id,
            context.organization_id,
            derived_location_id,
            type_,
            amount_minor,
            currency,
            from_account_id,
            to_account_id,
            derived_activity,
            effective_at,
            _text(description, 255),
            context.user_id,
            None,
            None,
            out_entry.id if out_entry else None,
            in_entry.id if in_entry else None,
            now,
        )
        try:
            if out_entry:
                await self.repository.add_cash_entry(out_entry)
            if in_entry:
                await self.repository.add_cash_entry(in_entry)
            await self.repository.add_cash_movement(value)
            await self.sink.stage(CashMovementPosted(context.organization_id, value.id))
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return value

    async def reverse_movement(
        self, context: TenantContext, movement_id: UUID
    ) -> CashMovement:
        try:
            value = await self.repository.get_cash_movement(
                context.organization_id, movement_id, lock=True
            )
            if value is None:
                raise FinanceNotFound("Cash movement not found")
            allowed = await allowed_locations(self.organizations, context)
            if allowed is not None and value not in await self.list_movements(context):
                raise FinanceNotFound("Cash movement not found")
            if value.reversed_at is not None:
                await self.repository.rollback()
                return value
            now = datetime.now(UTC)
            for role in ("OUT", "IN"):
                original = await self.repository.find_cash_entry(
                    value.organization_id, "CASH_MOVEMENT", value.id, role
                )
                if original is None:
                    continue
                await self.repository.add_cash_entry(
                    replace(
                        original,
                        id=uuid4(),
                        amount_minor=-original.amount_minor,
                        effective_at=now,
                        description="Cash movement reversal",
                        source_type="CASH_MOVEMENT_REVERSAL",
                        source_event_id=None,
                        entry_role=f"{role}_REVERSAL",
                        reversal_of_id=original.id,
                        created_at=now,
                    )
                )
            reversed_value = replace(
                value,
                reversed_by=context.user_id,
                reversed_at=now,
            )
            await self.repository.update_cash_movement(reversed_value)
            await self.sink.stage(CashMovementReversed(value.organization_id, value.id))
            await self.repository.commit()
            return reversed_value
        except Exception:
            await self.repository.rollback()
            raise


def _required_name(value: str) -> str:
    result = value.strip()
    if not result or len(result) > 150:
        raise InvalidFinanceOperation("Name must contain between 1 and 150 characters")
    return result


def _validate_shape(
    type_: CashMovementType,
    from_account_id: UUID | None,
    to_account_id: UUID | None,
) -> None:
    if from_account_id is not None and from_account_id == to_account_id:
        raise InvalidFinanceOperation("Cash movement accounts must differ")
    inflows = {CashMovementType.OWNER_CONTRIBUTION, CashMovementType.OTHER_INFLOW}
    outflows = {
        CashMovementType.SUPPLIER_PAYMENT,
        CashMovementType.OWNER_WITHDRAWAL,
        CashMovementType.OTHER_OUTFLOW,
    }
    valid = (
        type_ == CashMovementType.TRANSFER
        and from_account_id is not None
        and to_account_id is not None
    ) or (
        type_ in inflows and from_account_id is None and to_account_id is not None
    ) or (
        type_ in outflows and from_account_id is not None and to_account_id is None
    )
    if not valid:
        raise InvalidFinanceOperation("Cash movement accounts do not match its type")


def _activity(
    type_: CashMovementType, requested: CashFlowActivity | None
) -> CashFlowActivity:
    if type_ == CashMovementType.SUPPLIER_PAYMENT:
        return CashFlowActivity.OPERATING
    if type_ in {
        CashMovementType.OWNER_CONTRIBUTION,
        CashMovementType.OWNER_WITHDRAWAL,
    }:
        return CashFlowActivity.FINANCING
    return requested or CashFlowActivity.OPERATING
