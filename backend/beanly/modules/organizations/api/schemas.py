from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from beanly.modules.organizations.domain.enums import (
    LocationAccess,
    MembershipRole,
    OrganizationStatus,
)
from beanly.modules.organizations.domain.value_objects import (
    normalize_country_code,
    normalize_currency_code,
    normalize_timezone,
)

Name = Annotated[str, Field(min_length=1, max_length=150)]
Address = Annotated[str | None, Field(max_length=1000)]


class TenantContextResponse(BaseModel):
    organization_id: UUID
    user_id: UUID
    membership_id: UUID
    role: MembershipRole
    permissions: list[str]
    location_access: LocationAccess
    location_ids: list[UUID]


class FirstLocationRequest(BaseModel):
    name: Name
    timezone: Annotated[str, Field(min_length=1, max_length=100)]
    address: Address = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _name(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_timezone(value)

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return _address(value)


class CreateOrganizationRequest(BaseModel):
    name: Name
    country_code: str
    currency_code: str
    first_location: FirstLocationRequest

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _name(value)

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: str) -> str:
        return normalize_country_code(value)

    @field_validator("currency_code")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency_code(value)


class UpdateOrganizationRequest(BaseModel):
    name: Name | None = None
    country_code: str | None = None
    currency_code: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _name(value) if value is not None else None

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: str | None) -> str | None:
        return normalize_country_code(value) if value is not None else None

    @field_validator("currency_code")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return normalize_currency_code(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class CreateLocationRequest(BaseModel):
    name: Name
    timezone: Annotated[str, Field(min_length=1, max_length=100)]
    address: Address = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _name(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_timezone(value)

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return _address(value)


class UpdateLocationRequest(BaseModel):
    name: Name | None = None
    timezone: Annotated[str | None, Field(max_length=100)] = None
    address: Address = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _name(value) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return normalize_timezone(value) if value is not None else None

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return _address(value)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    country_code: str
    currency_code: str
    status: OrganizationStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    timezone: str
    address: str | None
    is_active: bool
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class MembershipResponse(BaseModel):
    role: str


class CreatedWorkspaceResponse(BaseModel):
    organization: OrganizationResponse
    location: LocationResponse
    membership: MembershipResponse


def _name(value: str) -> str:
    if not (normalized := value.strip()):
        raise ValueError("Name must not be blank")
    return normalized


def _address(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
