from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from beanly.modules.cash_management.domain.enums import (
    CashDrawerStatus,
    CashMovementKind,
    FiscalShiftStatus,
)

MoneyInput = Annotated[str, Field(pattern=r"^\d{1,19}$")]


class CashMovementRequest(BaseModel):
    client_movement_id: UUID
    amount_minor: MoneyInput
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    note: Annotated[str | None, Field(max_length=4000)] = None


class CashCloseRequest(BaseModel):
    client_close_id: UUID
    actual_cash_minor: MoneyInput
    note: Annotated[str | None, Field(max_length=4000)] = None
    pending_offline_operations: Annotated[int, Field(ge=0)] = 0


class VarianceApprovalRequest(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class CashDrawerResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    register_id: UUID
    shift_id: UUID
    currency_code: str
    status: CashDrawerStatus
    starting_cash_minor: str
    expected_cash_minor_snapshot: str | None
    actual_cash_minor: str | None
    variance_minor: str | None
    opened_by_user_id: UUID
    opened_at: datetime
    closed_by_user_id: UUID | None
    closed_at: datetime | None
    approved_by_user_id: UUID | None
    approved_at: datetime | None
    close_note: str | None
    client_open_id: UUID
    client_close_id: UUID | None
    version: int

    @classmethod
    def from_model(cls, value, *, expected_visible: bool = True) -> "CashDrawerResponse":
        money_fields = {
            "starting_cash_minor",
            "expected_cash_minor_snapshot",
            "actual_cash_minor",
            "variance_minor",
        }
        return cls(
            **{name: getattr(value, name) for name in cls.model_fields if name not in money_fields},
            starting_cash_minor=str(value.starting_cash_minor),
            expected_cash_minor_snapshot=_minor(value.expected_cash_minor_snapshot)
            if expected_visible
            else None,
            actual_cash_minor=_minor(value.actual_cash_minor),
            variance_minor=_minor(value.variance_minor) if expected_visible else None,
        )


class CashMovementResponse(BaseModel):
    id: UUID
    organization_id: UUID
    drawer_session_id: UUID
    kind: CashMovementKind
    amount_minor: str
    source_type: str
    source_id: UUID | None
    source_line_id: UUID | None
    client_movement_id: UUID | None
    reason: str | None
    note: str | None
    created_by_user_id: UUID | None
    occurred_at: datetime
    recorded_at: datetime

    @classmethod
    def from_model(cls, value) -> "CashMovementResponse":
        return cls(
            **{name: getattr(value, name) for name in cls.model_fields if name != "amount_minor"},
            amount_minor=str(value.amount_minor),
        )


class CashDrawerSummaryResponse(BaseModel):
    drawer: CashDrawerResponse
    expected_visible: bool
    starting_cash_minor: str | None
    cash_payments_minor: str | None
    cash_refunds_minor: str | None
    pay_in_minor: str | None
    pay_out_minor: str | None
    expected_cash_minor: str | None
    actual_cash_minor: str | None
    variance_minor: str | None

    @classmethod
    def from_result(
        cls, value: dict[str, object], *, expected_visible: bool
    ) -> "CashDrawerSummaryResponse":
        visible = (lambda key: str(value[key])) if expected_visible else (lambda key: None)
        return cls(
            drawer=CashDrawerResponse.from_model(
                value["drawer"], expected_visible=expected_visible
            ),
            expected_visible=expected_visible,
            starting_cash_minor=visible("starting_cash_minor"),
            cash_payments_minor=visible("cash_payments_minor"),
            cash_refunds_minor=visible("cash_refunds_minor"),
            pay_in_minor=visible("pay_in_minor"),
            pay_out_minor=visible("pay_out_minor"),
            expected_cash_minor=visible("expected_cash_minor"),
            actual_cash_minor=_minor(value["actual_cash_minor"]),
            variance_minor=_minor(value["variance_minor"]) if expected_visible else None,
        )


class CashDrawerReportRow(BaseModel):
    id: UUID
    location_id: UUID
    location_name: str
    register_id: UUID
    register_name: str
    shift_id: UUID
    cashier_user_id: UUID
    cashier_name: str
    status: CashDrawerStatus
    opened_at: datetime
    closed_at: datetime | None
    starting_cash_minor: str
    expected_cash_minor: str | None
    actual_cash_minor: str | None
    variance_minor: str | None
    currency_code: str


class CashDrawerDetailResponse(BaseModel):
    summary: CashDrawerSummaryResponse
    movements: list[CashMovementResponse]


class FiscalShiftStatusResponse(BaseModel):
    shift_id: UUID
    status: FiscalShiftStatus
    job_id: UUID | None
    job_type: str
    provider_code: str | None
    updated_at: datetime | None


def _minor(value) -> str | None:
    return str(value) if value is not None else None
