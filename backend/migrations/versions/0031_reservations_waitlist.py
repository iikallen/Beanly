"""Reservations, waitlist, and front-of-house seating.

Revision ID: 0031_reservations_waitlist
Revises: 0030_online_fulfillment
"""

import sqlalchemy as sa
from alembic import op

revision = "0031_reservations_waitlist"
down_revision = "0030_online_fulfillment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "reservation_locations",
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
        sa.Column("reservations_enabled", sa.Boolean(), nullable=False),
        sa.Column("default_duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("cleanup_buffer_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("minimum_lead_minutes", sa.Integer(), nullable=False),
        sa.Column("maximum_advance_days", sa.SmallInteger(), nullable=False),
        sa.Column("guest_cancellation_cutoff_minutes", sa.Integer(), nullable=False),
        sa.Column("maximum_party_size", sa.SmallInteger(), nullable=False),
        sa.Column("slot_interval_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "location_id", name="uq_reservation_location_scope"),
        sa.UniqueConstraint("public_slug", name="uq_reservation_location_slug"),
        sa.CheckConstraint(
            "default_duration_minutes BETWEEN 15 AND 480 AND "
            "cleanup_buffer_minutes BETWEEN 0 AND 240 AND "
            "minimum_lead_minutes BETWEEN 0 AND 43200 AND "
            "maximum_advance_days BETWEEN 1 AND 365 AND "
            "guest_cancellation_cutoff_minutes BETWEEN 0 AND 10080 AND "
            "maximum_party_size BETWEEN 1 AND 1000 AND "
            "slot_interval_minutes BETWEEN 5 AND 120",
            name="ck_reservation_location_policy",
        ),
    )
    op.create_index(
        "ix_reservation_locations_organization_id", "reservation_locations", ["organization_id"]
    )
    op.create_index(
        "ix_reservation_locations_location_id", "reservation_locations", ["location_id"]
    )
    op.create_table(
        "reservation_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "settings_id",
            sa.Uuid(),
            sa.ForeignKey("reservation_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("opens_at_local", sa.Time(), nullable=False),
        sa.Column("closes_at_local", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "location_id",
            "weekday",
            "opens_at_local",
            "closes_at_local",
            name="uq_reservation_schedule_range",
        ),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_reservation_schedule_weekday"),
        sa.CheckConstraint(
            "opens_at_local <> closes_at_local", name="ck_reservation_schedule_time"
        ),
    )
    op.create_index(
        "ix_reservation_schedules_organization_id", "reservation_schedules", ["organization_id"]
    )
    op.create_index(
        "ix_reservation_schedules_location_id", "reservation_schedules", ["location_id"]
    )
    op.create_table(
        "dining_sections",
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
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "organization_id", "location_id", name="uq_dining_section_scope"),
        sa.UniqueConstraint(
            "organization_id", "location_id", "name", name="uq_dining_section_name"
        ),
    )
    op.create_index("ix_dining_sections_organization_id", "dining_sections", ["organization_id"])
    op.create_index("ix_dining_sections_location_id", "dining_sections", ["location_id"])
    op.create_table(
        "dining_tables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("capacity", sa.SmallInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["section_id", "organization_id", "location_id"],
            [
                "dining_sections.id",
                "dining_sections.organization_id",
                "dining_sections.location_id",
            ],
            name="fk_dining_table_section_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "organization_id", "location_id", name="uq_dining_table_scope"),
        sa.UniqueConstraint(
            "organization_id", "location_id", "section_id", "name", name="uq_dining_table_name"
        ),
        sa.CheckConstraint("capacity > 0", name="ck_dining_table_capacity_positive"),
    )
    op.create_index("ix_dining_tables_organization_id", "dining_tables", ["organization_id"])
    op.create_index("ix_dining_tables_location_id", "dining_tables", ["location_id"])
    op.create_table(
        "reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("client_reservation_id", sa.Uuid(), nullable=False),
        sa.Column("guest_access_token_hash", sa.String(64), nullable=False),
        sa.Column("guest_name", sa.String(201), nullable=False),
        sa.Column("guest_phone", sa.String(32)),
        sa.Column("guest_email", sa.String(320)),
        sa.Column("party_size", sa.SmallInteger(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conflict_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dining_table_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("guest_notes", sa.Text()),
        sa.Column("internal_notes", sa.Text()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("seated_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("no_show_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dining_table_id", "organization_id", "location_id"],
            ["dining_tables.id", "dining_tables.organization_id", "dining_tables.location_id"],
            name="fk_reservation_table_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id", "client_reservation_id", name="uq_reservation_client"
        ),
        sa.UniqueConstraint("guest_access_token_hash", name="uq_reservation_guest_token"),
        sa.CheckConstraint("party_size > 0", name="ck_reservation_party_positive"),
        sa.CheckConstraint(
            "start_at < end_at AND end_at <= conflict_end_at", name="ck_reservation_period_order"
        ),
        sa.CheckConstraint(
            "status IN ('BOOKED','SEATED','COMPLETED','CANCELLED','NO_SHOW')",
            name="ck_reservation_status",
        ),
        sa.CheckConstraint("source IN ('GUEST','STAFF','POS')", name="ck_reservation_source"),
    )
    op.create_index("ix_reservations_organization_id", "reservations", ["organization_id"])
    op.create_index("ix_reservations_location_id", "reservations", ["location_id"])
    op.create_index("ix_reservation_location_start", "reservations", ["location_id", "start_at"])
    op.execute(
        "ALTER TABLE reservations ADD CONSTRAINT ex_reservation_table_period_active "
        "EXCLUDE USING gist (dining_table_id WITH =, "
        "tstzrange(start_at, conflict_end_at, '[)') WITH &&) "
        "WHERE (status = 'BOOKED')"
    )
    op.create_table(
        "waitlist_entries",
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
        sa.Column("client_entry_id", sa.Uuid(), nullable=False),
        sa.Column("guest_name", sa.String(201), nullable=False),
        sa.Column("guest_phone", sa.String(32)),
        sa.Column("guest_email", sa.String(320)),
        sa.Column("party_size", sa.SmallInteger(), nullable=False),
        sa.Column("quoted_wait_minutes", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("guest_notes", sa.Text()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("seated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "client_entry_id", name="uq_waitlist_client"),
        sa.CheckConstraint("party_size > 0", name="ck_waitlist_party_positive"),
        sa.CheckConstraint(
            "quoted_wait_minutes IS NULL OR quoted_wait_minutes >= 0",
            name="ck_waitlist_quote_nonnegative",
        ),
        sa.CheckConstraint("status IN ('WAITING','SEATED','CANCELLED')", name="ck_waitlist_status"),
    )
    op.create_index("ix_waitlist_entries_organization_id", "waitlist_entries", ["organization_id"])
    op.create_index("ix_waitlist_entries_location_id", "waitlist_entries", ["location_id"])
    op.create_index(
        "ix_waitlist_queue", "waitlist_entries", ["location_id", "status", "created_at", "id"]
    )
    op.create_table(
        "dining_visits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("client_action_id", sa.Uuid(), nullable=False),
        sa.Column("dining_table_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "waitlist_entry_id",
            sa.Uuid(),
            sa.ForeignKey("waitlist_entries.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "sales_order_id", sa.Uuid(), sa.ForeignKey("sales_orders.id", ondelete="RESTRICT")
        ),
        sa.Column("party_size", sa.SmallInteger(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dining_table_id", "organization_id", "location_id"],
            ["dining_tables.id", "dining_tables.organization_id", "dining_tables.location_id"],
            name="fk_dining_visit_table_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("organization_id", "client_action_id", name="uq_dining_visit_client"),
        sa.UniqueConstraint("reservation_id", name="uq_dining_visit_reservation"),
        sa.UniqueConstraint("waitlist_entry_id", name="uq_dining_visit_waitlist"),
        sa.UniqueConstraint("sales_order_id", name="uq_dining_visit_sales_order"),
        sa.CheckConstraint("party_size > 0", name="ck_dining_visit_party_positive"),
        sa.CheckConstraint(
            "NOT (reservation_id IS NOT NULL AND waitlist_entry_id IS NOT NULL)",
            name="ck_dining_visit_single_origin",
        ),
    )
    op.create_index("ix_dining_visits_organization_id", "dining_visits", ["organization_id"])
    op.create_index("ix_dining_visits_location_id", "dining_visits", ["location_id"])
    op.create_index(
        "uq_dining_visit_active_table",
        "dining_visits",
        ["dining_table_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("dining_visits")
    op.drop_table("waitlist_entries")
    op.drop_table("reservations")
    op.drop_table("dining_tables")
    op.drop_table("dining_sections")
    op.drop_table("reservation_schedules")
    op.drop_table("reservation_locations")
