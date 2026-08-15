"""First-party online and QR ordering.

Revision ID: 0029_online_ordering
Revises: 0027_kitchen_fulfillment
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_online_ordering"
down_revision = "0027_kitchen_fulfillment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sales_orders",
        sa.Column("order_source", sa.String(16), nullable=False, server_default="POS"),
    )
    op.create_check_constraint(
        "ck_sales_order_source",
        "sales_orders",
        "order_source IN ('POS','ONLINE','QR')",
    )
    op.create_index("ix_sales_orders_order_source", "sales_orders", ["order_source"])
    op.alter_column("sales_orders", "created_by_user_id", nullable=True)

    op.create_table(
        "promotion_channels",
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("channel", sa.String(16), primary_key=True),
        sa.CheckConstraint("channel IN ('POS','ONLINE','QR')", name="ck_promotion_channel"),
    )
    op.execute(
        sa.text(
            "INSERT INTO promotion_channels (promotion_id, channel) "
            "SELECT id, 'POS' FROM promotions"
        )
    )

    op.create_table(
        "online_ordering_locations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_slug", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("pickup_enabled", sa.Boolean(), nullable=False),
        sa.Column("qr_dine_in_enabled", sa.Boolean(), nullable=False),
        sa.Column("qr_auto_accept", sa.Boolean(), nullable=False),
        sa.Column(
            "register_id",
            sa.Uuid(),
            sa.ForeignKey("pos_registers.id", ondelete="RESTRICT"),
        ),
        sa.Column("accepting_orders", sa.Boolean(), nullable=False),
        sa.Column("manual_pause_reason", sa.String(500)),
        sa.Column("paused_until", sa.DateTime(timezone=True)),
        sa.Column("closed_date", sa.Date()),
        sa.Column("minimum_order_minor", sa.BigInteger(), nullable=False),
        sa.Column("maximum_order_minor", sa.BigInteger()),
        sa.Column("guest_name_required", sa.Boolean(), nullable=False),
        sa.Column("guest_phone_required_pickup", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "location_id", name="uq_online_location_scope"
        ),
        sa.UniqueConstraint("public_slug", name="uq_online_location_slug"),
        sa.CheckConstraint(
            "minimum_order_minor >= 0", name="ck_online_location_minimum_nonnegative"
        ),
        sa.CheckConstraint(
            "maximum_order_minor IS NULL OR maximum_order_minor >= minimum_order_minor",
            name="ck_online_location_maximum_bounded",
        ),
    )
    op.create_index(
        "ix_online_ordering_locations_organization_id",
        "online_ordering_locations",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_ordering_locations_location_id",
        "online_ordering_locations",
        ["location_id"],
    )

    op.create_table(
        "online_ordering_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "location_config_id",
            sa.Uuid(),
            sa.ForeignKey("online_ordering_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("opens_at_local", sa.Time(), nullable=False),
        sa.Column("closes_at_local", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "location_id",
            "weekday",
            "opens_at_local",
            "closes_at_local",
            name="uq_online_schedule_range",
        ),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_online_schedule_weekday"),
        sa.CheckConstraint("opens_at_local <> closes_at_local", name="ck_online_schedule_time"),
    )
    op.create_index(
        "ix_online_ordering_schedules_organization_id",
        "online_ordering_schedules",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_schedule_location_weekday",
        "online_ordering_schedules",
        ["location_id", "weekday"],
    )

    op.create_table(
        "online_ordering_stations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("public_token_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_token_hash", name="uq_online_station_token"),
        sa.CheckConstraint(
            "kind IN ('TABLE','COUNTER','PICKUP_SPOT')", name="ck_online_station_kind"
        ),
    )
    op.create_index(
        "ix_online_ordering_stations_organization_id",
        "online_ordering_stations",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_ordering_stations_location_id",
        "online_ordering_stations",
        ["location_id"],
    )
    op.create_index(
        "ix_online_station_location_active",
        "online_ordering_stations",
        ["location_id", "is_active"],
    )

    op.create_table(
        "online_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sales_order_id",
            sa.Uuid(),
            sa.ForeignKey("sales_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("online_ordering_stations.id", ondelete="RESTRICT"),
        ),
        sa.Column("client_order_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("guest_name_snapshot", sa.String(201)),
        sa.Column("guest_phone_snapshot", sa.String(32)),
        sa.Column("station_label_snapshot", sa.String(100)),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("quote_revision", sa.String(96), nullable=False),
        sa.Column("status_token_hash", sa.String(64), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.String(1000)),
        sa.Column("cancelled_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(1000)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("preparing_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "client_order_id", name="uq_online_order_client"
        ),
        sa.UniqueConstraint("sales_order_id", name="uq_online_order_sales_order"),
        sa.UniqueConstraint("status_token_hash", name="uq_online_order_status_token"),
        sa.CheckConstraint("source IN ('ONLINE','QR')", name="ck_online_order_source"),
        sa.CheckConstraint(
            "status IN ('PENDING','AWAITING_PAYMENT','PAID','PREPARING','READY',"
            "'COMPLETED','REJECTED','CANCELLED')",
            name="ck_online_order_status",
        ),
        sa.CheckConstraint(
            "subtotal_minor >= 0 AND discount_minor >= 0 AND total_minor >= 0 "
            "AND discount_minor <= subtotal_minor "
            "AND total_minor = subtotal_minor - discount_minor",
            name="ck_online_order_money",
        ),
    )
    for name, columns in (
        ("ix_online_orders_organization_id", ["organization_id"]),
        ("ix_online_orders_location_id", ["location_id"]),
        ("ix_online_orders_sales_order_id", ["sales_order_id"]),
        ("ix_online_orders_status", ["status"]),
        ("ix_online_order_location_status", ["location_id", "status", "created_at"]),
    ):
        op.create_index(name, "online_orders", columns)

    op.create_table(
        "online_order_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "online_order_id",
            sa.Uuid(),
            sa.ForeignKey("online_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(24)),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("client_action_id", sa.Uuid()),
        sa.Column("source_event_id", sa.Uuid()),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_online_order_actions_organization_id",
        "online_order_actions",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_order_actions_order",
        "online_order_actions",
        ["online_order_id", "created_at"],
    )
    op.create_index(
        "uq_online_order_action_client",
        "online_order_actions",
        ["organization_id", "client_action_id"],
        unique=True,
        postgresql_where=sa.text("client_action_id IS NOT NULL"),
        sqlite_where=sa.text("client_action_id IS NOT NULL"),
    )
    op.create_index(
        "uq_online_order_action_event",
        "online_order_actions",
        ["organization_id", "source_event_id"],
        unique=True,
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
        sqlite_where=sa.text("source_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    for table in (
        "online_order_actions",
        "online_orders",
        "online_ordering_stations",
        "online_ordering_schedules",
        "online_ordering_locations",
        "promotion_channels",
    ):
        op.drop_table(table)
    op.execute(
        sa.text(
            "UPDATE sales_orders SET created_by_user_id = organizations.created_by "
            "FROM organizations WHERE sales_orders.organization_id = organizations.id "
            "AND sales_orders.created_by_user_id IS NULL"
        )
    )
    op.alter_column("sales_orders", "created_by_user_id", nullable=False)
    op.drop_index("ix_sales_orders_order_source", table_name="sales_orders")
    op.drop_constraint("ck_sales_order_source", "sales_orders", type_="check")
    op.drop_column("sales_orders", "order_source")
