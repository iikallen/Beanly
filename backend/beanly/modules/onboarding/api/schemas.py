from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.onboarding.domain.enums import (
    ImportEntityType,
    ImportResolution,
    ImportSourceType,
    ImportStatus,
    OnboardingStatus,
    UploadSourceType,
)

MinorAmount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,15})$")]


class OnboardingStepResponse(BaseModel):
    status: Literal["COMPLETE", "NEEDS_ATTENTION", "OPTIONAL", "MISSING"]
    count: int = 0
    details: list[str] = Field(default_factory=list)


class OnboardingStatusResponse(BaseModel):
    status: OnboardingStatus
    current_step: str | None
    steps: dict[str, OnboardingStepResponse]
    pos_ready: bool
    ai_available: bool
    started_at: datetime | None
    completed_at: datetime | None
    dismissed_at: datetime | None


class BootstrapRequest(BaseModel):
    warehouse_name: str = Field(default="Main Stock", min_length=1, max_length=150)
    register_name: str = Field(default="Main POS", min_length=1, max_length=150)

    @field_validator("warehouse_name", "register_name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


class BootstrapCreatedResponse(BaseModel):
    warehouse: bool
    register_created: bool = Field(validation_alias="register", serialization_alias="register")


class BootstrapResponse(BaseModel):
    location_id: UUID
    warehouse_id: UUID
    register_id: UUID
    created: BootstrapCreatedResponse
    onboarding: OnboardingStatusResponse


class CapabilityResponse(BaseModel):
    available: bool
    reason: str | None = None


class PosterCapabilityResponse(CapabilityResponse):
    real_fixture_verified: bool
    extensions: list[str]


class SpreadsheetCapabilityResponse(BaseModel):
    csv: bool
    xlsx: bool
    max_bytes: int


class OnboardingCapabilitiesResponse(BaseModel):
    ai: CapabilityResponse
    poster: PosterCapabilityResponse
    spreadsheet: SpreadsheetCapabilityResponse


class TemplateSummaryResponse(BaseModel):
    code: str
    version: int
    name: str
    description: str
    category_count: int
    product_count: int
    has_draft_recipes: bool


class TemplateListResponse(BaseModel):
    items: list[TemplateSummaryResponse]
    spreadsheet_download_url: str


class TemplateOptionsRequest(BaseModel):
    sizes: list[str] = Field(default_factory=list, max_length=12)
    alternative_milks: list[str] = Field(default_factory=list, max_length=12)
    extras: list[str] = Field(default_factory=list, max_length=24)
    packaging: bool = True
    include_draft_recipes: bool = False

    @field_validator("sizes", "alternative_milks", "extras")
    @classmethod
    def unique_nonblank(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            key = value.casefold()
            if not value or len(value) > 100:
                raise ValueError("Template option must contain 1-100 characters")
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result


class TemplatePreviewRequest(BaseModel):
    client_import_id: UUID
    version: int = Field(default=1, ge=1, le=2_147_483_647)
    location_id: UUID
    options: TemplateOptionsRequest = Field(default_factory=TemplateOptionsRequest)


class ImportEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    entity_type: ImportEntityType
    source_key: str
    payload: dict[str, object]
    resolution: ImportResolution
    target_id: UUID | None
    error_codes: list[str]
    warning_codes: list[str]
    sort_order: int


class ImportRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    client_import_id: UUID
    source_type: ImportSourceType
    source_name: str
    source_version: int | None
    file_name: str | None
    file_hash: str | None
    status: ImportStatus
    entity_count: int
    error_count: int
    warning_count: int
    payload_hash: str
    mapping: dict[str, str]
    duplicate_file_run_id: UUID | None = None
    duplicate_warning: str | None = None
    created_by: UUID
    created_at: datetime
    applied_at: datetime | None
    failed_at: datetime | None
    entities: list[ImportEntityResponse]


class ImportRunListResponse(BaseModel):
    items: list["ImportRunSummaryResponse"]
    total: int
    limit: int
    offset: int


class ImportUploadMetadata(BaseModel):
    client_import_id: UUID
    location_id: UUID
    source_type: UploadSourceType = UploadSourceType.AUTO


class ImportInspectSheetResponse(BaseModel):
    name: str
    columns: list[str]


class ImportInspectResponse(BaseModel):
    file_hash: str
    source_type: ImportSourceType
    sheets: list[ImportInspectSheetResponse]
    mapping_required: bool


class ImportEntityPatchRequest(BaseModel):
    resolution: ImportResolution
    target_id: UUID | None = None
    payload: dict[str, object] | None = None

    @field_validator("target_id")
    @classmethod
    def target_matches_resolution(cls, value: UUID | None, info):
        resolution = info.data.get("resolution")
        if resolution is ImportResolution.MATCH_EXISTING and value is None:
            raise ValueError("target_id is required for MATCH_EXISTING")
        if resolution is not ImportResolution.MATCH_EXISTING and value is not None:
            raise ValueError("target_id is only allowed for MATCH_EXISTING")
        return value


class ImportValidationResponse(BaseModel):
    run: ImportRunResponse
    valid: bool
    error_count: int
    warning_count: int


class BulkPriceRowRequest(BaseModel):
    entity_id: UUID
    price_minor: MinorAmount

    @field_validator("price_minor")
    @classmethod
    def bounded_minor_amount(cls, value: str) -> str:
        if int(value) > MAX_NUMERIC_20_6_MINOR:
            raise ValueError("price_minor exceeds the supported monetary range")
        return value


class ImportRunSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    location_id: UUID
    client_import_id: UUID
    source_type: ImportSourceType
    source_name: str
    source_version: int | None
    file_name: str | None
    file_hash: str | None
    status: ImportStatus
    entity_count: int
    error_count: int
    warning_count: int
    payload_hash: str
    mapping: dict[str, str]
    duplicate_file_run_id: UUID | None = None
    duplicate_warning: str | None = None
    created_by: UUID
    created_at: datetime
    applied_at: datetime | None
    failed_at: datetime | None


class BulkPriceRequest(BaseModel):
    rows: list[BulkPriceRowRequest] = Field(min_length=1, max_length=10000)


class ActivateReadyRequest(BaseModel):
    product_ids: list[UUID] = Field(min_length=1, max_length=10000)
    confirm_starter_recipes_reviewed: bool = False


class ProductReadinessResponse(BaseModel):
    product_id: UUID
    ready: bool
    reasons: list[str]


class ActivateReadyResponse(BaseModel):
    items: list[ProductReadinessResponse]
    activated_count: int


class PublicMenuUrlRequest(BaseModel):
    client_import_id: UUID
    location_id: UUID
    public_menu_url: str = Field(min_length=8, max_length=2048, pattern=r"^https?://")
