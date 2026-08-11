"""Add offline-first POS devices, sessions, snapshots and sync receipts.

Revision ID: 0020_offline_pos
Revises: 0019_production_hardening
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_offline_pos"
down_revision: str | None = "0019_production_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pos_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("register_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_pos_device_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["register_id"], ["pos_registers.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_hash"),
    )
    for column in ("organization_id", "location_id", "register_id", "status"):
        op.create_index(f"ix_pos_devices_{column}", "pos_devices", [column])
    op.create_index(
        "uq_pos_devices_active_register",
        "pos_devices",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "pos_catalog_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("public_payload", postgresql.JSONB(), nullable=False),
        sa.Column("private_payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "location_id", "warehouse_id", "expires_at", "payload_hash"):
        op.create_index(f"ix_pos_catalog_snapshots_{column}", "pos_catalog_snapshots", [column])

    op.create_table(
        "pos_offline_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("register_id", sa.Uuid(), nullable=False),
        sa.Column("shift_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'CLOSED', 'REVOKED', 'EXPIRED')",
            name="ck_pos_offline_session_status",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["pos_devices.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["register_id"], ["pos_registers.id"]),
        sa.ForeignKeyConstraint(["shift_id"], ["register_shifts.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["catalog_snapshot_id"], ["pos_catalog_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "device_id",
        "organization_id",
        "location_id",
        "register_id",
        "shift_id",
        "status",
        "expires_at",
    ):
        op.create_index(f"ix_pos_offline_sessions_{column}", "pos_offline_sessions", [column])
    op.create_index(
        "uq_pos_offline_sessions_active_device",
        "pos_offline_sessions",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.add_column(
        "sales_orders", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("sales_orders", sa.Column("pos_device_id", sa.Uuid(), nullable=True))
    op.add_column("sales_orders", sa.Column("offline_session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sales_orders", sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sales_orders", sa.Column("offline_display_number", sa.BigInteger(), nullable=True)
    )
    op.create_check_constraint("ck_sales_order_version_positive", "sales_orders", "version > 0")
    op.create_foreign_key(
        "fk_sales_orders_pos_device", "sales_orders", "pos_devices", ["pos_device_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_sales_orders_offline_session",
        "sales_orders",
        "pos_offline_sessions",
        ["offline_session_id"],
        ["id"],
    )
    op.create_index("ix_sales_orders_pos_device_id", "sales_orders", ["pos_device_id"])
    op.create_index("ix_sales_orders_offline_session_id", "sales_orders", ["offline_session_id"])

    op.add_column("payments", sa.Column("offline_session_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_payments_offline_session",
        "payments",
        "pos_offline_sessions",
        ["offline_session_id"],
        ["id"],
    )
    op.create_index("ix_payments_offline_session_id", "payments", ["offline_session_id"])

    op.create_table(
        "pos_offline_order_syncs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("client_order_id", sa.Uuid(), nullable=False),
        sa.Column("server_order_id", sa.Uuid(), nullable=True),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("server_order_number", sa.BigInteger(), nullable=True),
        sa.Column("last_client_revision", sa.Integer(), nullable=False),
        sa.Column("last_server_version", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("last_client_revision > 0", name="ck_pos_order_sync_revision_positive"),
        sa.CheckConstraint("status IN ('SYNCED', 'CONFLICT')", name="ck_pos_order_sync_status"),
        sa.ForeignKeyConstraint(["session_id"], ["pos_offline_sessions.id"]),
        sa.ForeignKeyConstraint(["server_order_id"], ["sales_orders.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "client_order_id"),
    )
    op.create_index(
        "ix_pos_offline_order_syncs_session_id", "pos_offline_order_syncs", ["session_id"]
    )

    op.drop_constraint("ck_sales_order_cogs_status", "sales_orders", type_="check")
    op.create_check_constraint(
        "ck_sales_order_cogs_status",
        "sales_orders",
        "cogs_status IS NULL OR cogs_status IN ('COMPLETE', 'INCOMPLETE', 'ESTIMATED')",
    )
    op.drop_constraint("ck_finance_entry_quality", "finance_entries", type_="check")
    op.create_check_constraint(
        "ck_finance_entry_quality",
        "finance_entries",
        "(entry_type = 'COGS' AND quality_status IS NOT NULL "
        "AND quality_status IN ('COMPLETE','INCOMPLETE','ESTIMATED')) OR "
        "(entry_type <> 'COGS' AND quality_status IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_finance_entry_quality", "finance_entries", type_="check")
    op.execute(
        "UPDATE finance_entries SET quality_status = 'INCOMPLETE' "
        "WHERE quality_status = 'ESTIMATED'"
    )
    op.create_check_constraint(
        "ck_finance_entry_quality",
        "finance_entries",
        "(entry_type = 'COGS' AND quality_status IS NOT NULL "
        "AND quality_status IN ('COMPLETE','INCOMPLETE')) OR "
        "(entry_type <> 'COGS' AND quality_status IS NULL)",
    )
    op.drop_constraint("ck_sales_order_cogs_status", "sales_orders", type_="check")
    op.execute(
        "UPDATE sales_orders SET cogs_status = 'INCOMPLETE' "
        "WHERE cogs_status = 'ESTIMATED'"
    )
    op.create_check_constraint(
        "ck_sales_order_cogs_status",
        "sales_orders",
        "cogs_status IS NULL OR cogs_status IN ('COMPLETE', 'INCOMPLETE')",
    )
    op.drop_table("pos_offline_order_syncs")
    op.drop_index("ix_payments_offline_session_id", table_name="payments")
    op.drop_constraint("fk_payments_offline_session", "payments", type_="foreignkey")
    op.drop_column("payments", "offline_session_id")
    op.drop_index("ix_sales_orders_offline_session_id", table_name="sales_orders")
    op.drop_index("ix_sales_orders_pos_device_id", table_name="sales_orders")
    op.drop_constraint("fk_sales_orders_offline_session", "sales_orders", type_="foreignkey")
    op.drop_constraint("fk_sales_orders_pos_device", "sales_orders", type_="foreignkey")
    op.drop_constraint("ck_sales_order_version_positive", "sales_orders", type_="check")
    for column in (
        "offline_display_number",
        "client_created_at",
        "offline_session_id",
        "pos_device_id",
        "version",
    ):
        op.drop_column("sales_orders", column)
    op.drop_table("pos_offline_sessions")
    op.drop_table("pos_catalog_snapshots")
    op.drop_table("pos_devices")
