from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Password = Annotated[str, Field(min_length=8, max_length=128)]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    first_name: Name
    last_name: Name

    @field_validator("first_name", "last_name")
    @classmethod
    def names_must_not_be_blank(cls, value: str) -> str:
        if not (stripped := value.strip()):
            raise ValueError("must not be blank")
        return stripped


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    is_active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
