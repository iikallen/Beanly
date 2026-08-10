from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExpenseCreated:
    organization_id: UUID
    expense_id: UUID


@dataclass(frozen=True, slots=True)
class ExpensePosted:
    organization_id: UUID
    expense_id: UUID


@dataclass(frozen=True, slots=True)
class ExpenseReversed:
    organization_id: UUID
    expense_id: UUID


@dataclass(frozen=True, slots=True)
class CashMovementPosted:
    organization_id: UUID
    cash_movement_id: UUID


@dataclass(frozen=True, slots=True)
class CashMovementReversed:
    organization_id: UUID
    cash_movement_id: UUID
