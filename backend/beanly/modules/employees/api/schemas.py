from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from beanly.modules.employees.domain.enums import EmployeeStatus

ShortText = Annotated[str, Field(min_length=1, max_length=100)]


class CreateEmployeeRequest(BaseModel):
    first_name: ShortText
    last_name: ShortText
    phone: Annotated[str | None, Field(max_length=40)] = None
    position: Annotated[str | None, Field(max_length=100)] = None
    location_ids: Annotated[list[UUID], Field(min_length=1)]

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("Value must not be blank")
        return normalized

    @field_validator("phone", "position")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("location_ids")
    @classmethod
    def unique_locations(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Location ids must be unique")
        return value


class UpdateEmployeeRequest(BaseModel):
    first_name: ShortText | None = None
    last_name: ShortText | None = None
    phone: Annotated[str | None, Field(max_length=40)] = None
    position: Annotated[str | None, Field(max_length=100)] = None
    location_ids: Annotated[list[UUID] | None, Field(min_length=1)] = None

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (normalized := value.strip()):
            raise ValueError("Value must not be blank")
        return normalized

    @field_validator("phone", "position")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("location_ids")
    @classmethod
    def unique_locations(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Location ids must be unique")
        return value

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID | None
    first_name: str
    last_name: str
    phone: str | None
    position: str | None
    status: EmployeeStatus
    location_ids: tuple[UUID, ...]
    created_at: datetime
    updated_at: datetime
