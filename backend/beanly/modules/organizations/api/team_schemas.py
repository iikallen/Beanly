from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from beanly.modules.organizations.domain.enums import (
    InvitationStatus,
    LocationAccess,
    MembershipRole,
)


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: MembershipRole
    location_ids: Annotated[list[UUID], Field(min_length=1)]
    employee_id: UUID | None = None

    @field_validator("location_ids")
    @classmethod
    def unique_locations(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Location ids must be unique")
        return value


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    employee_id: UUID | None
    email: str
    role: MembershipRole
    status: InvitationStatus
    expires_at: datetime
    invited_by: UUID
    accepted_by: UUID | None
    accepted_at: datetime | None
    location_ids: tuple[UUID, ...]
    created_at: datetime


class PublicInvitationResponse(BaseModel):
    organization_name: str
    email: str
    role: MembershipRole
    expires_at: datetime


class TeamMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID | None
    user_id: UUID | None
    first_name: str
    last_name: str
    phone: str | None
    position: str | None
    email: str | None
    role: MembershipRole | None
    status: str
    location_access: LocationAccess | None
    locations: tuple[str, ...]


class TeamResponse(BaseModel):
    members: list[TeamMemberResponse]
    invitations: list[InvitationResponse]
    permissions: list[str]
