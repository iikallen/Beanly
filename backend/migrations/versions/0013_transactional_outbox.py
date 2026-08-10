"""Add the transactional event outbox.

Revision ID: 0013_transactional_outbox
Revises: 0012_sale_posting
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_transactional_outbox"
down_revision: str | None = "0012_sale_posting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("event_name", sa.String(150), nullable=False),
        sa.Column("event_version", sa.SmallInteger(), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=True),
        sa.Column("aggregate_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_version > 0", name="ck_outbox_event_version_positive"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
        sa.CheckConstraint(
            "(locked_by IS NULL) = (locked_until IS NULL)",
            name="ck_outbox_lock_pair",
        ),
        sa.CheckConstraint(
            "processed_at IS NULL OR dead_lettered_at IS NULL",
            name="ck_outbox_terminal_state",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox_events",
        ["available_at", "occurred_at"],
        postgresql_where=sa.text(
            "processed_at IS NULL AND dead_lettered_at IS NULL"
        ),
    )
    op.create_index(
        "ix_outbox_events_organization_id",
        "outbox_events",
        ["organization_id"],
    )
    op.create_index("ix_outbox_event_name", "outbox_events", ["event_name"])
    op.create_index(
        "ix_outbox_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id"],
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
