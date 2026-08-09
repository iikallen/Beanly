"""Add employees, invitations, roles, and location access.

Revision ID: 0003_team
Revises: 0002_organizations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_team"
down_revision: str | None = "0002_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE organization_memberships SET status = upper(status)")
    op.add_column(
        "organization_memberships",
        sa.Column(
            "location_access",
            sa.String(length=20),
            server_default="SELECTED",
            nullable=False,
        ),
    )
    op.execute("UPDATE organization_memberships SET location_access = 'ALL' WHERE role = 'OWNER'")

    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("position", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id"),
    )
    op.create_index("ix_employees_organization_id", "employees", ["organization_id"])
    op.create_index("ix_employees_user_id", "employees", ["user_id"])

    op.create_table(
        "membership_locations",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["membership_id"], ["organization_memberships.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("membership_id", "location_id"),
    )
    op.create_index(
        "ix_membership_locations_membership_id",
        "membership_locations",
        ["membership_id"],
    )
    op.create_index(
        "ix_membership_locations_location_id",
        "membership_locations",
        ["location_id"],
    )

    op.create_table(
        "employee_locations",
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("employee_id", "location_id"),
    )
    op.create_index("ix_employee_locations_employee_id", "employee_locations", ["employee_id"])
    op.create_index("ix_employee_locations_location_id", "employee_locations", ["location_id"])

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=False),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organization_invitations_organization_id",
        "organization_invitations",
        ["organization_id"],
    )
    op.create_index("ix_organization_invitations_email", "organization_invitations", ["email"])
    op.create_index(
        "ix_organization_invitations_token_hash",
        "organization_invitations",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "uq_pending_invitation_organization_email",
        "organization_invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "organization_invitation_locations",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invitation_id"], ["organization_invitations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("invitation_id", "location_id"),
    )
    op.create_index(
        "ix_organization_invitation_locations_invitation_id",
        "organization_invitation_locations",
        ["invitation_id"],
    )
    op.create_index(
        "ix_organization_invitation_locations_location_id",
        "organization_invitation_locations",
        ["location_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_invitation_locations_location_id",
        table_name="organization_invitation_locations",
    )
    op.drop_index(
        "ix_organization_invitation_locations_invitation_id",
        table_name="organization_invitation_locations",
    )
    op.drop_table("organization_invitation_locations")
    op.drop_index(
        "uq_pending_invitation_organization_email",
        table_name="organization_invitations",
    )
    op.drop_index(
        "ix_organization_invitations_token_hash",
        table_name="organization_invitations",
    )
    op.drop_index("ix_organization_invitations_email", table_name="organization_invitations")
    op.drop_index(
        "ix_organization_invitations_organization_id",
        table_name="organization_invitations",
    )
    op.drop_table("organization_invitations")
    op.drop_index("ix_employee_locations_location_id", table_name="employee_locations")
    op.drop_index("ix_employee_locations_employee_id", table_name="employee_locations")
    op.drop_table("employee_locations")
    op.drop_index("ix_membership_locations_location_id", table_name="membership_locations")
    op.drop_index("ix_membership_locations_membership_id", table_name="membership_locations")
    op.drop_table("membership_locations")
    op.drop_index("ix_employees_user_id", table_name="employees")
    op.drop_index("ix_employees_organization_id", table_name="employees")
    op.drop_table("employees")
    op.drop_column("organization_memberships", "location_access")
    op.execute("UPDATE organization_memberships SET status = lower(status) WHERE status = 'ACTIVE'")
