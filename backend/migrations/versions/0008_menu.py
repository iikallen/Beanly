"""Add menu products, variants, recipes and location overrides.

Revision ID: 0008_menu
Revises: 0007_inventory_valuation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_menu"
down_revision: str | None = "0007_inventory_valuation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "menu_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_menu_categories_organization_id", "menu_categories", ["organization_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')", name="ck_product_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["menu_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("organization_id", "category_id", "status", "name"):
        op.create_index(f"ix_products_{name}", "products", [name])
    op.create_index("ix_products_organization_name", "products", ["organization_id", "name"])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("base_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("base_price_minor >= 0", name="ck_variant_base_price"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')", name="ck_variant_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_variants_organization_id", "product_variants", ["organization_id"])
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])
    op.create_index(
        "uq_product_variants_organization_sku",
        "product_variants",
        ["organization_id", "sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
    )
    op.create_index(
        "uq_product_variants_active_default",
        "product_variants",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND status <> 'ARCHIVED'"),
    )

    op.create_table(
        "variant_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price_minor >= 0", name="ck_variant_price_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(
            ["product_variant_id"], ["product_variants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "product_variant_id"),
    )
    for name in ("organization_id", "location_id", "product_variant_id"):
        op.create_index(f"ix_variant_prices_{name}", "variant_prices", [name])

    op.create_table(
        "product_location_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "product_id"),
    )
    for name in ("organization_id", "location_id", "product_id"):
        op.create_index(f"ix_product_location_settings_{name}", "product_location_settings", [name])

    op.create_table(
        "recipes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("yield_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("yield_quantity > 0", name="ck_recipe_yield_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["product_variant_id"], ["product_variants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_variant_id"),
    )
    op.create_index("ix_recipes_organization_id", "recipes", ["organization_id"])
    op.create_index("ix_recipes_product_variant_id", "recipes", ["product_variant_id"])

    op.create_table(
        "recipe_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_recipe_component_quantity_positive"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "inventory_item_id"),
    )
    op.create_index("ix_recipe_components_recipe_id", "recipe_components", ["recipe_id"])
    op.create_index(
        "ix_recipe_components_inventory_item_id", "recipe_components", ["inventory_item_id"]
    )


def downgrade() -> None:
    op.drop_table("recipe_components")
    op.drop_table("recipes")
    op.drop_table("product_location_settings")
    op.drop_table("variant_prices")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("menu_categories")
