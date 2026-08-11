from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_RATE = Decimal("999.9999")


def _decimal_string(value: object) -> object:
    if value is not None and not isinstance(value, str):
        raise ValueError("Decimal values must be strings")
    return value


class TaxProfileUpsertRequest(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)
    tax_regime_code: str = Field(min_length=1, max_length=64)
    vat_registered: bool
    default_vat_rate: Decimal | None = Field(default=None, ge=0, le=_MAX_RATE, allow_inf_nan=False)
    effective_from: date

    _exact_rate = field_validator("default_vat_rate", mode="before")(_decimal_string)


class TaxProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    id: UUID
    organization_id: UUID
    country_code: str
    tax_regime_code: str
    vat_registered: bool
    default_vat_rate: str | None
    effective_from: date
    effective_to: date | None
    created_by: UUID
    created_at: datetime


class FiscalVariantUpsertRequest(BaseModel):
    fiscal_name: str = Field(min_length=1, max_length=300)
    nkt_code: str | None = Field(default=None, max_length=100)
    nkt_code_type: str | None = Field(default=None, max_length=20)
    fiscal_unit_code: str = Field(min_length=1, max_length=50)
    vat_rate_override: Decimal | None = Field(default=None, ge=0, le=_MAX_RATE, allow_inf_nan=False)
    requires_marking: bool = False

    _exact_rate = field_validator("vat_rate_override", mode="before")(_decimal_string)


class FiscalVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    id: UUID
    organization_id: UUID
    product_variant_id: UUID
    fiscal_name: str
    nkt_code: str | None
    nkt_code_type: str | None
    fiscal_unit_code: str
    vat_rate_override: str | None
    requires_marking: bool
    updated_at: datetime


class UnmappedVariantResponse(BaseModel):
    variant_id: UUID
    name: str
    reason: str


class FiscalReadinessResponse(BaseModel):
    ready: bool
    readiness_percent: int = Field(ge=0, le=100)
    tax_profile: str
    location: str
    unmapped_variants: list[UnmappedVariantResponse]
