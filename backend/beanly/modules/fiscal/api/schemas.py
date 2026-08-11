from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from beanly.modules.fiscal.domain.enums import (
    FiscalEnforcementMode,
    FiscalReceiptSource,
    FiscalReceiptStatus,
    FiscalRouteSourceMode,
)

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
    nkt_verified_at: datetime | None
    nkt_external_product_id: str | None
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


class NktProductResponse(BaseModel):
    external_id: str
    ntin: str
    gtins: list[str]
    name_ru: str
    name_kk: str
    category_code: str
    unit_code: str | None
    status: str
    updated_at: datetime | None


class NktVariantLinkRequest(BaseModel):
    ntin: str = Field(pattern=r"^[0-9]{13}$")


class FiscalReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    connection_id: UUID
    source_type: FiscalReceiptSource
    source_id: UUID
    provider_code: str
    status: FiscalReceiptStatus
    external_receipt_id: str | None
    receipt_number: str | None
    receipt_url: str | None
    provider_request_id: str | None
    provider_correlation_id: str
    fiscalized_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime


class FiscalReceiptListResponse(BaseModel):
    items: list[FiscalReceiptResponse]
    total: int
    limit: int
    offset: int


class FiscalOperationsResponse(BaseModel):
    provider_code: str | None
    connected: bool
    receipts_today: int
    successful_today: int
    pending: int
    failed: int
    unknown: int
    oldest_pending_seconds: int | None


class FiscalEnforcementRequest(BaseModel):
    mode: FiscalEnforcementMode


class FiscalEnforcementResponse(BaseModel):
    location_id: UUID
    mode: FiscalEnforcementMode


class FiscalRouteCreateRequest(BaseModel):
    location_id: UUID
    register_id: UUID
    provider_connection_id: UUID
    source_mode: FiscalRouteSourceMode
    is_active: bool = True


class FiscalRoutePatchRequest(BaseModel):
    is_active: bool


class FiscalRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    register_id: UUID
    provider_connection_id: UUID
    source_mode: FiscalRouteSourceMode
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GoLiveReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]
