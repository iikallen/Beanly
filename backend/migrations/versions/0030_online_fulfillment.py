"""Online fulfillment, delivery zones, slots, and lifecycle context.

Revision ID: 0030_online_fulfillment
Revises: 0029_online_ordering
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_online_fulfillment"
down_revision = "0029_online_ordering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preparation_minutes", sa.SmallInteger(), nullable=False, server_default="15"),
        sa.Column("slot_interval_minutes", sa.SmallInteger(), nullable=False, server_default="15"),
        sa.Column("slot_capacity", sa.SmallInteger(), nullable=False, server_default="20"),
        sa.Column("max_advance_minutes", sa.BigInteger(), nullable=False, server_default="10080"),
        sa.Column(
            "cancellation_cutoff_minutes", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "delivery_minimum_order_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "default_fulfillment_type",
            sa.String(16),
            nullable=False,
            server_default="PICKUP",
        ),
    ):
        op.add_column("online_ordering_locations", column)
    op.create_check_constraint(
        "ck_online_location_fulfillment",
        "online_ordering_locations",
        "preparation_minutes BETWEEN 0 AND 240 AND "
        "slot_interval_minutes BETWEEN 5 AND 120 AND slot_capacity BETWEEN 1 AND 1000 AND "
        "max_advance_minutes BETWEEN 15 AND 43200 AND "
        "cancellation_cutoff_minutes BETWEEN 0 AND 1440 AND "
        "delivery_minimum_order_minor >= 0 AND "
        "default_fulfillment_type IN ('PICKUP','DELIVERY')",
    )

    op.add_column(
        "sales_orders",
        sa.Column("fulfillment_fee_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_sales_order_fulfillment_fee_nonnegative",
        "sales_orders",
        "fulfillment_fee_minor >= 0",
    )
    op.add_column(
        "online_orders",
        sa.Column("fulfillment_fee_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.drop_constraint("ck_online_order_money", "online_orders", type_="check")
    op.create_check_constraint(
        "ck_online_order_money",
        "online_orders",
        "subtotal_minor >= 0 AND discount_minor >= 0 AND fulfillment_fee_minor >= 0 "
        "AND total_minor >= 0 AND discount_minor <= subtotal_minor "
        "AND total_minor = subtotal_minor - discount_minor + fulfillment_fee_minor",
    )

    op.add_column(
        "refunds",
        sa.Column("fulfillment_fee_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_refund_fulfillment_fee_nonnegative", "refunds", "fulfillment_fee_minor >= 0"
    )
    op.add_column("kitchen_tickets", sa.Column("fulfillment_type", sa.String(16)))
    op.add_column("kitchen_tickets", sa.Column("order_source", sa.String(16)))
    op.add_column(
        "kitchen_tickets", sa.Column("promised_at", sa.DateTime(timezone=True))
    )
    op.add_column("kitchen_tickets", sa.Column("guest_instructions", sa.Text()))
    op.drop_constraint("ck_kitchen_work_status", "kitchen_work_items", type_="check")
    op.create_check_constraint(
        "ck_kitchen_work_status",
        "kitchen_work_items",
        "status IN ('QUEUED','PREPARING','READY','CANCELLED')",
    )

    op.create_table(
        "online_delivery_zones",
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
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("delivery_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("minimum_order_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "location_id", "name", name="uq_online_delivery_zone_name"
        ),
        sa.CheckConstraint(
            "delivery_fee_minor >= 0 AND minimum_order_minor >= 0",
            name="ck_online_delivery_zone_money",
        ),
    )
    op.create_index(
        "ix_online_delivery_zones_organization_id",
        "online_delivery_zones",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_delivery_zones_location_id", "online_delivery_zones", ["location_id"]
    )
    op.create_index(
        "ix_online_delivery_zone_location_enabled",
        "online_delivery_zones",
        ["location_id", "enabled"],
    )

    op.create_table(
        "online_order_fulfillments",
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
            "online_order_id",
            sa.Uuid(),
            sa.ForeignKey("online_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fulfillment_type", sa.String(16), nullable=False),
        sa.Column("fulfillment_timing", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("promised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "delivery_zone_id",
            sa.Uuid(),
            sa.ForeignKey("online_delivery_zones.id", ondelete="RESTRICT"),
        ),
        sa.Column("delivery_address", sa.Text()),
        sa.Column("guest_instructions", sa.Text()),
        sa.Column("fulfillment_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("online_order_id", name="uq_online_order_fulfillment_order"),
        sa.CheckConstraint(
            "fulfillment_type IN ('PICKUP','DELIVERY')", name="ck_online_fulfillment_type"
        ),
        sa.CheckConstraint(
            "fulfillment_timing IN ('ASAP','SCHEDULED')",
            name="ck_online_fulfillment_timing",
        ),
        sa.CheckConstraint(
            "fulfillment_fee_minor >= 0", name="ck_online_fulfillment_fee"
        ),
        sa.CheckConstraint(
            "(fulfillment_timing = 'ASAP' AND requested_at IS NULL) OR "
            "(fulfillment_timing = 'SCHEDULED' AND requested_at IS NOT NULL)",
            name="ck_online_fulfillment_requested_at",
        ),
        sa.CheckConstraint(
            "(fulfillment_type = 'DELIVERY' AND delivery_zone_id IS NOT NULL "
            "AND delivery_address IS NOT NULL) OR "
            "(fulfillment_type <> 'DELIVERY' AND delivery_zone_id IS NULL "
            "AND delivery_address IS NULL)",
            name="ck_online_fulfillment_delivery_shape",
        ),
    )
    op.create_index(
        "ix_online_order_fulfillments_organization_id",
        "online_order_fulfillments",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_order_fulfillments_location_id",
        "online_order_fulfillments",
        ["location_id"],
    )
    op.create_index(
        "ix_online_fulfillment_location_promised",
        "online_order_fulfillments",
        ["location_id", "promised_at"],
    )
    op.execute(
        sa.text(
            "INSERT INTO online_order_fulfillments "
            "(id, organization_id, location_id, online_order_id, fulfillment_type, "
            "fulfillment_timing, requested_at, promised_at, delivery_zone_id, "
            "delivery_address, guest_instructions, fulfillment_fee_minor, created_at, updated_at) "
            "SELECT id, organization_id, location_id, id, 'PICKUP', 'ASAP', NULL, "
            "date_trunc('minute', created_at), NULL, NULL, NULL, 0, created_at, updated_at "
            "FROM online_orders"
        )
    )

    op.create_table(
        "online_fulfillment_reservations",
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
        sa.Column(
            "online_order_id",
            sa.Uuid(),
            sa.ForeignKey("online_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slot_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("online_order_id", name="uq_online_reservation_order"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','RELEASED','CONSUMED')",
            name="ck_online_reservation_status",
        ),
    )
    op.create_index(
        "ix_online_fulfillment_reservations_organization_id",
        "online_fulfillment_reservations",
        ["organization_id"],
    )
    op.create_index(
        "ix_online_fulfillment_reservations_location_id",
        "online_fulfillment_reservations",
        ["location_id"],
    )
    op.create_index(
        "ix_online_reservation_capacity",
        "online_fulfillment_reservations",
        ["location_id", "slot_start_at", "status"],
    )


def downgrade() -> None:
    op.drop_table("online_fulfillment_reservations")
    op.drop_table("online_order_fulfillments")
    op.drop_table("online_delivery_zones")

    op.execute(
        sa.text(
            "UPDATE kitchen_work_items SET status = 'READY' WHERE status = 'CANCELLED'"
        )
    )
    op.drop_constraint("ck_kitchen_work_status", "kitchen_work_items", type_="check")
    op.create_check_constraint(
        "ck_kitchen_work_status",
        "kitchen_work_items",
        "status IN ('QUEUED','PREPARING','READY')",
    )

    for name in (
        "guest_instructions",
        "promised_at",
        "order_source",
        "fulfillment_type",
    ):
        op.drop_column("kitchen_tickets", name)
    op.drop_constraint(
        "ck_refund_fulfillment_fee_nonnegative", "refunds", type_="check"
    )
    op.drop_column("refunds", "fulfillment_fee_minor")
    op.drop_constraint("ck_online_order_money", "online_orders", type_="check")
    op.create_check_constraint(
        "ck_online_order_money",
        "online_orders",
        "subtotal_minor >= 0 AND discount_minor >= 0 AND total_minor >= 0 "
        "AND discount_minor <= subtotal_minor "
        "AND total_minor = subtotal_minor - discount_minor",
    )
    op.drop_column("online_orders", "fulfillment_fee_minor")
    op.drop_constraint(
        "ck_sales_order_fulfillment_fee_nonnegative", "sales_orders", type_="check"
    )
    op.drop_column("sales_orders", "fulfillment_fee_minor")
    op.drop_constraint(
        "ck_online_location_fulfillment", "online_ordering_locations", type_="check"
    )
    for name in (
        "default_fulfillment_type",
        "delivery_minimum_order_minor",
        "cancellation_cutoff_minutes",
        "max_advance_minutes",
        "slot_capacity",
        "slot_interval_minutes",
        "preparation_minutes",
        "delivery_enabled",
    ):
        op.drop_column("online_ordering_locations", name)
