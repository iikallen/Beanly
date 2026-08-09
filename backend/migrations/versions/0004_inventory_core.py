"""Create inventory core tables.

Revision ID: 0004_inventory_core
Revises: 0003_team
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_inventory_core"
down_revision: str | None = "0003_team"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_warehouses_organization_id", "warehouses", ["organization_id"])
    op.create_index("ix_warehouses_location_id", "warehouses", ["location_id"])

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("base_unit", sa.String(8), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("base_unit IN ('g', 'ml', 'pcs')", name="ck_item_base_unit"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_items_organization_id", "inventory_items", ["organization_id"])
    op.create_index(
        "uq_inventory_items_organization_sku",
        "inventory_items",
        ["organization_id", "sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
        sqlite_where=sa.text("sku IS NOT NULL"),
    )

    op.create_table(
        "stock_balances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "inventory_item_id"),
    )
    op.create_index("ix_stock_balances_organization_id", "stock_balances", ["organization_id"])
    op.create_index("ix_stock_balances_location_id", "stock_balances", ["location_id"])
    op.create_index("ix_stock_balances_warehouse_id", "stock_balances", ["warehouse_id"])
    op.create_index("ix_stock_balances_inventory_item_id", "stock_balances", ["inventory_item_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_balances_inventory_item_id", table_name="stock_balances")
    op.drop_index("ix_stock_balances_warehouse_id", table_name="stock_balances")
    op.drop_index("ix_stock_balances_location_id", table_name="stock_balances")
    op.drop_index("ix_stock_balances_organization_id", table_name="stock_balances")
    op.drop_table("stock_balances")
    op.drop_index("uq_inventory_items_organization_sku", table_name="inventory_items")
    op.drop_index("ix_inventory_items_organization_id", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_index("ix_warehouses_location_id", table_name="warehouses")
    op.drop_index("ix_warehouses_organization_id", table_name="warehouses")
    op.drop_table("warehouses")
