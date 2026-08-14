"""Kitchen display system and order fulfillment.

Revision ID: 0027_kitchen_fulfillment
Revises: 0026_cash_management
"""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027_kitchen_fulfillment"
down_revision = "0026_cash_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kitchen_stations",
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
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("warning_after_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("late_after_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("location_id", "code", name="uq_kitchen_station_location_code"),
        sa.CheckConstraint("role IN ('PREP','EXPO','PREP_EXPO')", name="ck_kitchen_station_role"),
        sa.CheckConstraint("warning_after_seconds > 0", name="ck_kitchen_station_warning"),
        sa.CheckConstraint(
            "late_after_seconds > warning_after_seconds", name="ck_kitchen_station_late"
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_kitchen_station_sort"),
    )
    op.create_index("ix_kitchen_stations_organization_id", "kitchen_stations", ["organization_id"])
    op.create_index("ix_kitchen_stations_location_id", "kitchen_stations", ["location_id"])
    op.create_index(
        "ix_kitchen_station_location_active", "kitchen_stations", ["location_id", "is_active"]
    )
    op.create_index(
        "uq_kitchen_station_location_default",
        "kitchen_stations",
        ["location_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )
    op.create_table(
        "kitchen_routing_rules",
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
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("kitchen_stations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column(
            "category_id", sa.Uuid(), sa.ForeignKey("menu_categories.id", ondelete="CASCADE")
        ),
        sa.Column(
            "variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="CASCADE")
        ),
        sa.Column("order_type", sa.String(16)),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('CATEGORY','VARIANT')", name="ck_kitchen_routing_scope"),
        sa.CheckConstraint(
            "(scope = 'CATEGORY' AND category_id IS NOT NULL "
            "AND variant_id IS NULL) OR (scope = 'VARIANT' "
            "AND variant_id IS NOT NULL AND category_id IS NULL)",
            name="ck_kitchen_routing_target",
        ),
        sa.CheckConstraint(
            "order_type IS NULL OR order_type IN ('DINE_IN','TAKEAWAY','DELIVERY')",
            name="ck_kitchen_routing_order_type",
        ),
    )
    for name, columns in (
        ("ix_kitchen_routing_rules_organization_id", ["organization_id"]),
        ("ix_kitchen_routing_rules_location_id", ["location_id"]),
        ("ix_kitchen_routing_rules_station_id", ["station_id"]),
        ("ix_kitchen_routing_location_active", ["location_id", "is_active"]),
        ("ix_kitchen_routing_variant", ["variant_id"]),
        ("ix_kitchen_routing_category", ["category_id"]),
    ):
        op.create_index(name, "kitchen_routing_rules", columns)
    op.create_table(
        "kitchen_tickets",
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
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("sales_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            sa.Uuid(),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "shift_id",
            sa.Uuid(),
            sa.ForeignKey("register_shifts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_number", sa.BigInteger(), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("customer_id", sa.Uuid()),
        sa.Column("customer_name", sa.String(201)),
        sa.Column("customer_phone", sa.String(32)),
        sa.Column("table_label", sa.String(100)),
        sa.Column("guest_count", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("organization_id", "order_id", name="uq_kitchen_ticket_order"),
        sa.CheckConstraint(
            "status IN ('QUEUED','PREPARING','READY','COMPLETED','CANCELLED')",
            name="ck_kitchen_ticket_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_kitchen_ticket_version"),
    )
    for name, columns in (
        ("ix_kitchen_tickets_organization_id", ["organization_id"]),
        ("ix_kitchen_tickets_location_id", ["location_id"]),
        ("ix_kitchen_tickets_order_id", ["order_id"]),
        ("ix_kitchen_tickets_shift_id", ["shift_id"]),
        ("ix_kitchen_tickets_status", ["status"]),
        ("ix_kitchen_ticket_location_status", ["location_id", "status"]),
        ("ix_kitchen_ticket_location_version", ["location_id", "version"]),
    ):
        op.create_index(name, "kitchen_tickets", columns)
    op.create_table(
        "kitchen_ticket_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.Uuid(),
            sa.ForeignKey("kitchen_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("variant_name", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("ticket_id", "order_item_id", name="uq_kitchen_ticket_order_item"),
        sa.CheckConstraint("quantity > 0", name="ck_kitchen_ticket_item_quantity"),
        sa.CheckConstraint("sort_order >= 0", name="ck_kitchen_ticket_item_sort"),
    )
    op.create_index("ix_kitchen_ticket_items_ticket_id", "kitchen_ticket_items", ["ticket_id"])
    op.create_table(
        "kitchen_ticket_item_modifiers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ticket_item_id",
            sa.Uuid(),
            sa.ForeignKey("kitchen_ticket_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("modifier_group_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_group_name", sa.String(150), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_name", sa.String(150), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "ticket_item_id", "modifier_option_id", name="uq_kitchen_ticket_modifier_option"
        ),
    )
    op.create_index(
        "ix_kitchen_ticket_item_modifiers_ticket_item_id",
        "kitchen_ticket_item_modifiers",
        ["ticket_item_id"],
    )
    op.create_table(
        "kitchen_work_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "ticket_id",
            sa.Uuid(),
            sa.ForeignKey("kitchen_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_item_id",
            sa.Uuid(),
            sa.ForeignKey("kitchen_ticket_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "station_id",
            sa.Uuid(),
            sa.ForeignKey("kitchen_stations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ticket_item_id", "station_id", name="uq_kitchen_work_item_route"),
        sa.CheckConstraint(
            "status IN ('QUEUED','PREPARING','READY')", name="ck_kitchen_work_status"
        ),
    )
    for name, columns in (
        ("ix_kitchen_work_items_organization_id", ["organization_id"]),
        ("ix_kitchen_work_items_location_id", ["location_id"]),
        ("ix_kitchen_work_items_ticket_id", ["ticket_id"]),
        ("ix_kitchen_work_items_ticket_item_id", ["ticket_item_id"]),
        ("ix_kitchen_work_items_station_id", ["station_id"]),
        ("ix_kitchen_work_items_status", ["status"]),
        ("ix_kitchen_work_station_status", ["station_id", "status"]),
    ):
        op.create_index(name, "kitchen_work_items", columns)
    op.create_table(
        "kitchen_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("client_action_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "result_payload",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "client_action_id", name="uq_kitchen_action_client"),
        sa.CheckConstraint(
            "action_type IN ('START','READY','COMPLETE','RECALL')", name="ck_kitchen_action_type"
        ),
    )
    op.create_index("ix_kitchen_actions_organization_id", "kitchen_actions", ["organization_id"])
    op.create_index("ix_kitchen_actions_location_id", "kitchen_actions", ["location_id"])
    _backfill_default_stations()


def _backfill_default_stations() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)
    locations = bind.execute(sa.text("SELECT id, organization_id FROM locations")).mappings()
    for row in locations:
        station_id = uuid5(NAMESPACE_URL, f"beanly:kitchen:default:{row['id']}")
        bind.execute(
            sa.text(
                "INSERT INTO kitchen_stations "
                "(id, organization_id, location_id, name, code, role, "
                "is_default, is_active, warning_after_seconds, "
                "late_after_seconds, sort_order, created_at, updated_at) "
                "VALUES (:id, :organization_id, :location_id, 'Preparation', "
                "'PREPARATION', 'PREP_EXPO', true, true, 600, 900, 0, :now, :now)"
            ),
            {
                "id": station_id,
                "organization_id": row["organization_id"],
                "location_id": row["id"],
                "now": now,
            },
        )


def downgrade() -> None:
    for table in (
        "kitchen_actions",
        "kitchen_work_items",
        "kitchen_ticket_item_modifiers",
        "kitchen_ticket_items",
        "kitchen_tickets",
        "kitchen_routing_rules",
        "kitchen_stations",
    ):
        op.drop_table(table)
