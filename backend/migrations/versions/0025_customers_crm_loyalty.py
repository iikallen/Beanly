"""Customers, CRM and loyalty.

Revision ID: 0025_customers_crm_loyalty
Revises: 0024_promotions_pricing
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_customers_crm_loyalty"
down_revision = "0024_promotions_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone_normalized", sa.String(32), nullable=False),
        sa.Column("phone_display", sa.String(32), nullable=False),
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("email", sa.String(320)),
        sa.Column("birth_date", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "phone_normalized", name="uq_customers_org_phone"),
    )
    op.create_index(
        "ix_customers_org_name", "customers", ["organization_id", "last_name", "first_name"]
    )
    op.create_index("ix_customers_org_active", "customers", ["organization_id", "deleted_at"])

    op.create_table(
        "loyalty_programs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("earn_rate_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("point_value_minor", sa.BigInteger(), nullable=False, server_default="100"),
        sa.Column("birthday_reward_points", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", name="uq_loyalty_programs_org"),
        sa.CheckConstraint(
            "earn_rate_bps >= 0 AND earn_rate_bps <= 10000", name="ck_loyalty_program_earn"
        ),
        sa.CheckConstraint("point_value_minor > 0", name="ck_loyalty_program_point_value"),
        sa.CheckConstraint("birthday_reward_points >= 0", name="ck_loyalty_program_birthday"),
    )
    op.create_table(
        "loyalty_tiers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("threshold_lifetime_points", sa.BigInteger(), nullable=False),
        sa.Column("earn_multiplier_bps", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_loyalty_tiers_org_name"),
        sa.UniqueConstraint(
            "organization_id", "threshold_lifetime_points", name="uq_loyalty_tiers_org_threshold"
        ),
        sa.CheckConstraint("threshold_lifetime_points >= 0", name="ck_loyalty_tier_threshold"),
        sa.CheckConstraint(
            "earn_multiplier_bps >= 0 AND earn_multiplier_bps <= 100000",
            name="ck_loyalty_tier_multiplier",
        ),
    )
    op.create_index(
        "ix_loyalty_tiers_org_threshold",
        "loyalty_tiers",
        ["organization_id", "threshold_lifetime_points"],
    )
    op.create_table(
        "loyalty_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tier_id", sa.Uuid(), sa.ForeignKey("loyalty_tiers.id", ondelete="SET NULL")),
        sa.Column("points_balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lifetime_earned_points", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "customer_id", name="uq_loyalty_accounts_customer"),
        sa.CheckConstraint("lifetime_earned_points >= 0", name="ck_loyalty_account_lifetime"),
    )
    op.create_table(
        "loyalty_ledger_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("points_delta", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("related_source_id", sa.String(100)),
        sa.Column("reason", sa.String(1000)),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "customer_id",
            "kind",
            "source_type",
            "source_id",
            name="uq_loyalty_ledger_source",
        ),
        sa.CheckConstraint("points_delta <> 0", name="ck_loyalty_ledger_nonzero"),
        sa.CheckConstraint(
            "kind IN ('EARN','REDEEM','REFUND_REVERSAL','REDEMPTION_REVERSAL',"
            "'ADJUSTMENT','BIRTHDAY_REWARD')",
            name="ck_loyalty_ledger_kind",
        ),
    )
    op.create_index(
        "ix_loyalty_ledger_customer_time",
        "loyalty_ledger_entries",
        ["organization_id", "customer_id", "occurred_at"],
    )
    op.create_index(
        "uq_loyalty_adjustment_org_client",
        "loyalty_ledger_entries",
        ["organization_id", "source_id"],
        unique=True,
        postgresql_where=sa.text(
            "kind = 'ADJUSTMENT' AND source_type = 'CLIENT_ADJUSTMENT'"
        ),
        sqlite_where=sa.text(
            "kind = 'ADJUSTMENT' AND source_type = 'CLIENT_ADJUSTMENT'"
        ),
    )

    op.add_column("sales_orders", sa.Column("customer_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sales_orders", sa.Column("customer_name_snapshot", sa.String(201), nullable=True)
    )
    op.add_column(
        "sales_orders", sa.Column("customer_phone_snapshot", sa.String(32), nullable=True)
    )
    op.create_foreign_key(
        "fk_sales_orders_customer",
        "sales_orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_sales_orders_customer_id", "sales_orders", ["customer_id"])

    op.create_table(
        "loyalty_redemptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("sales_orders.id"), nullable=False),
        sa.Column("client_redemption_id", sa.Uuid(), nullable=False),
        sa.Column("points_requested", sa.BigInteger(), nullable=False),
        sa.Column("points_applied", sa.BigInteger()),
        sa.Column("discount_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "organization_id", "client_redemption_id", name="uq_loyalty_redemption_client"
        ),
        sa.UniqueConstraint("order_id", name="uq_loyalty_redemption_order"),
        sa.CheckConstraint("points_requested > 0", name="ck_loyalty_redemption_points"),
        sa.CheckConstraint(
            "points_applied IS NULL OR (points_applied > 0 AND points_applied <= points_requested)",
            name="ck_loyalty_redemption_applied",
        ),
        sa.CheckConstraint("discount_minor > 0", name="ck_loyalty_redemption_discount"),
        sa.CheckConstraint(
            "status IN ('RESERVED','APPLIED','REVERSED')", name="ck_loyalty_redemption_status"
        ),
    )
    op.create_table(
        "promotion_audiences",
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False, server_default="ALL"),
        sa.Column("tier_id", sa.Uuid(), sa.ForeignKey("loyalty_tiers.id", ondelete="CASCADE")),
        sa.CheckConstraint(
            "kind IN ('ALL','CUSTOMER','TIER','BIRTHDAY')", name="ck_promotion_audience_kind"
        ),
        sa.CheckConstraint(
            "(kind = 'TIER' AND tier_id IS NOT NULL) OR (kind <> 'TIER' AND tier_id IS NULL)",
            name="ck_promotion_audience_tier",
        ),
    )
    op.create_table(
        "promotion_audience_customers",
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotion_audiences.promotion_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.add_column("sales_order_discounts", sa.Column("audience_kind", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_order_discount_audience",
        "sales_order_discounts",
        "audience_kind IS NULL OR audience_kind IN ('CUSTOMER','TIER','BIRTHDAY')",
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION prevent_loyalty_ledger_mutation() RETURNS trigger AS $$ "
            "BEGIN "
            "IF TG_OP = 'DELETE' AND NOT EXISTS "
            "(SELECT 1 FROM organizations WHERE id = OLD.organization_id) THEN "
            "RETURN OLD; "
            "END IF; "
            "RAISE EXCEPTION 'loyalty ledger is immutable'; "
            "END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER trg_loyalty_ledger_immutable BEFORE UPDATE OR DELETE ON "
            "loyalty_ledger_entries FOR EACH ROW EXECUTE FUNCTION prevent_loyalty_ledger_mutation()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_loyalty_ledger_immutable ON loyalty_ledger_entries")
        op.execute("DROP FUNCTION IF EXISTS prevent_loyalty_ledger_mutation()")
    op.drop_constraint("ck_order_discount_audience", "sales_order_discounts", type_="check")
    op.drop_column("sales_order_discounts", "audience_kind")
    op.drop_table("promotion_audience_customers")
    op.drop_table("promotion_audiences")
    op.drop_table("loyalty_redemptions")
    op.drop_index("ix_sales_orders_customer_id", table_name="sales_orders")
    op.drop_constraint("fk_sales_orders_customer", "sales_orders", type_="foreignkey")
    op.drop_column("sales_orders", "customer_phone_snapshot")
    op.drop_column("sales_orders", "customer_name_snapshot")
    op.drop_column("sales_orders", "customer_id")
    op.drop_table("loyalty_ledger_entries")
    op.drop_table("loyalty_accounts")
    op.drop_table("loyalty_tiers")
    op.drop_table("loyalty_programs")
    op.drop_table("customers")
