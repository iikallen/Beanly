"""Add management finance ledgers and documents.

Revision ID: 0015_finance
Revises: 0014_inventory_operations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_finance"
down_revision: str | None = "0014_inventory_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name"),
    )
    op.create_index(
        "ix_expense_categories_organization_id", "expense_categories", ["organization_id"]
    )

    op.create_table(
        "cash_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("system_key", sa.String(80), nullable=True),
        sa.Column(
            "opening_balance_minor",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('CASH','CARD_CLEARING','BANK','OTHER')",
            name="ck_cash_account_type",
        ),
        sa.CheckConstraint(
            "length(currency_code) = 3", name="ck_cash_account_currency"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "location_id", "system_key"),
    )
    op.create_index("ix_cash_accounts_organization_id", "cash_accounts", ["organization_id"])
    op.create_index("ix_cash_accounts_location_id", "cash_accounts", ["location_id"])

    op.create_table(
        "finance_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("entry_type", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("expense_category_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("entry_role", sa.String(80), nullable=False),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("quality_status", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('REVENUE','COGS','INVENTORY_LOSS','INVENTORY_GAIN',"
            "'OPERATING_EXPENSE','OTHER_INCOME','OTHER_EXPENSE')",
            name="ck_finance_entry_type",
        ),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_finance_currency"),
        sa.CheckConstraint(
            "(entry_type = 'COGS' AND quality_status IS NOT NULL "
            "AND quality_status IN ('COMPLETE','INCOMPLETE')) OR "
            "(entry_type <> 'COGS' AND quality_status IS NULL)",
            name="ck_finance_entry_quality",
        ),
        sa.ForeignKeyConstraint(["expense_category_id"], ["expense_categories.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["finance_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id", "entry_role"),
        sa.UniqueConstraint("source_type", "source_id", "entry_role"),
    )
    for column in ("organization_id", "location_id", "effective_at", "entry_type"):
        op.create_index(f"ix_finance_entries_{column}", "finance_entries", [column])
    op.create_index(
        "ix_finance_entries_org_effective",
        "finance_entries",
        ["organization_id", "effective_at"],
    )
    op.create_index(
        "ix_finance_entries_source", "finance_entries", ["source_type", "source_id"]
    )

    op.create_table(
        "cash_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("cash_account_id", sa.Uuid(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("cash_flow_activity", sa.String(20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("entry_role", sa.String(80), nullable=False),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cash_flow_activity IN ('OPERATING','INVESTING','FINANCING')",
            name="ck_cash_entry_activity",
        ),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_cash_entry_currency"),
        sa.ForeignKeyConstraint(["cash_account_id"], ["cash_accounts.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["cash_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id", "entry_role"),
        sa.UniqueConstraint("source_type", "source_id", "entry_role"),
    )
    for column in (
        "organization_id",
        "location_id",
        "cash_account_id",
        "cash_flow_activity",
        "effective_at",
    ):
        op.create_index(f"ix_cash_entries_{column}", "cash_entries", [column])
    op.create_index(
        "ix_cash_entries_org_account_effective",
        "cash_entries",
        ["organization_id", "cash_account_id", "effective_at"],
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("cash_account_id", sa.Uuid(), nullable=True),
        sa.Column("vendor", sa.String(200), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finance_entry_id", sa.Uuid(), nullable=True),
        sa.Column("cash_entry_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_expense_amount_positive"),
        sa.CheckConstraint(
            "status IN ('DRAFT','POSTED','REVERSED')", name="ck_expense_status"
        ),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_expense_currency"),
        sa.ForeignKeyConstraint(["cash_account_id"], ["cash_accounts.id"]),
        sa.ForeignKeyConstraint(["cash_entry_id"], ["cash_entries.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["expense_categories.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["finance_entry_id"], ["finance_entries.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cash_entry_id"),
        sa.UniqueConstraint("finance_entry_id"),
        sa.UniqueConstraint("organization_id", "number"),
    )
    for column in ("organization_id", "location_id", "category_id", "status", "occurred_at"):
        op.create_index(f"ix_expenses_{column}", "expenses", [column])
    op.create_index(
        "ix_expenses_org_occurred", "expenses", ["organization_id", "occurred_at"]
    )

    op.create_table(
        "cash_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("from_account_id", sa.Uuid(), nullable=True),
        sa.Column("to_account_id", sa.Uuid(), nullable=True),
        sa.Column("cash_flow_activity", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("out_entry_id", sa.Uuid(), nullable=True),
        sa.Column("in_entry_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_cash_movement_amount_positive"),
        sa.CheckConstraint(
            "type IN ('SUPPLIER_PAYMENT','OWNER_CONTRIBUTION','OWNER_WITHDRAWAL',"
            "'OTHER_INFLOW','OTHER_OUTFLOW','TRANSFER')",
            name="ck_cash_movement_type",
        ),
        sa.CheckConstraint(
            "cash_flow_activity IN ('OPERATING','INVESTING','FINANCING')",
            name="ck_cash_movement_activity",
        ),
        sa.CheckConstraint(
            "(type = 'TRANSFER' AND from_account_id IS NOT NULL AND to_account_id IS NOT NULL "
            "AND from_account_id <> to_account_id) OR "
            "(type IN ('OWNER_CONTRIBUTION','OTHER_INFLOW') AND from_account_id IS NULL "
            "AND to_account_id IS NOT NULL) OR "
            "(type IN ('SUPPLIER_PAYMENT','OWNER_WITHDRAWAL','OTHER_OUTFLOW') "
            "AND from_account_id IS NOT NULL AND to_account_id IS NULL)",
            name="ck_cash_movement_accounts",
        ),
        sa.CheckConstraint(
            "(type = 'SUPPLIER_PAYMENT' AND cash_flow_activity = 'OPERATING') OR "
            "(type IN ('OWNER_CONTRIBUTION','OWNER_WITHDRAWAL') "
            "AND cash_flow_activity = 'FINANCING') OR "
            "type IN ('OTHER_INFLOW','OTHER_OUTFLOW','TRANSFER')",
            name="ck_cash_movement_derived_activity",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["from_account_id"], ["cash_accounts.id"]),
        sa.ForeignKeyConstraint(["in_entry_id"], ["cash_entries.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["out_entry_id"], ["cash_entries.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_account_id"], ["cash_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("in_entry_id"),
        sa.UniqueConstraint("out_entry_id"),
    )
    for column in ("organization_id", "location_id", "type", "occurred_at"):
        op.create_index(f"ix_cash_movements_{column}", "cash_movements", [column])
    op.create_index(
        "ix_cash_movements_org_occurred",
        "cash_movements",
        ["organization_id", "occurred_at"],
    )


def downgrade() -> None:
    for table in (
        "cash_movements",
        "expenses",
        "cash_entries",
        "finance_entries",
        "cash_accounts",
        "expense_categories",
    ):
        op.drop_table(table)
