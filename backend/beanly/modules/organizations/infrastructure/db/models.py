from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    country_code: Mapped[str] = mapped_column(String(2))
    currency_code: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class LocationModel(Base):
    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint(
            "fiscal_enforcement_mode IN ('DISABLED','TEST','LIVE_REQUIRED')",
            name="ck_location_fiscal_enforcement_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    timezone: Mapped[str] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    fiscal_enforcement_mode: Mapped[str] = mapped_column(
        String(24), default="DISABLED", server_default=text("'DISABLED'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OrganizationMembershipModel(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    location_access: Mapped[str] = mapped_column(String(20), default="SELECTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MembershipLocationModel(Base):
    __tablename__ = "membership_locations"

    membership_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organization_memberships.id"), primary_key=True, index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OrganizationInvitationModel(Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        Index(
            "uq_pending_invitation_organization_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    accepted_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InvitationLocationModel(Base):
    __tablename__ = "organization_invitation_locations"

    invitation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organization_invitations.id"), primary_key=True, index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
