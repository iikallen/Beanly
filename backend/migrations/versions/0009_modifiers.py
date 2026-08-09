"""Add variant modifier groups, options, recipe deltas and location overrides.

Revision ID: 0009_modifiers
Revises: 0008_menu
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_modifiers"
down_revision: str | None = "0008_menu"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "modifier_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("selection_type", sa.String(16), nullable=False),
        sa.Column("min_selections", sa.Integer(), nullable=False),
        sa.Column("max_selections", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "selection_type IN ('SINGLE', 'MULTIPLE')", name="ck_modifier_group_selection_type"
        ),
        sa.CheckConstraint("min_selections >= 0", name="ck_modifier_group_min_nonnegative"),
        sa.CheckConstraint("max_selections >= 1", name="ck_modifier_group_max_positive"),
        sa.CheckConstraint("min_selections <= max_selections", name="ck_modifier_group_min_max"),
        sa.CheckConstraint(
            "selection_type <> 'SINGLE' OR max_selections = 1", name="ck_modifier_group_single_max"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["product_variant_id"], ["product_variants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_modifier_groups_organization_id", "modifier_groups", ["organization_id"])
    op.create_index(
        "ix_modifier_groups_product_variant_id", "modifier_groups", ["product_variant_id"]
    )

    op.create_table(
        "modifier_options",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("base_price_delta_minor", sa.BigInteger(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "base_price_delta_minor >= 0", name="ck_modifier_option_price_nonnegative"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["modifier_group_id"], ["modifier_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_modifier_options_organization_id", "modifier_options", ["organization_id"])
    op.create_index(
        "ix_modifier_options_modifier_group_id", "modifier_options", ["modifier_group_id"]
    )

    op.create_table(
        "modifier_option_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(20, 6), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_modifier_component_quantity_nonzero"),
        sa.ForeignKeyConstraint(
            ["modifier_option_id"], ["modifier_options.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("modifier_option_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_modifier_option_components_modifier_option_id",
        "modifier_option_components",
        ["modifier_option_id"],
    )
    op.create_index(
        "ix_modifier_option_components_inventory_item_id",
        "modifier_option_components",
        ["inventory_item_id"],
    )

    op.create_table(
        "modifier_option_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.Column("price_delta_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price_delta_minor >= 0", name="ck_modifier_price_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(
            ["modifier_option_id"], ["modifier_options.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "modifier_option_id"),
    )
    for column in ("organization_id", "location_id", "modifier_option_id"):
        op.create_index(f"ix_modifier_option_prices_{column}", "modifier_option_prices", [column])

    op.create_table(
        "modifier_option_location_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(
            ["modifier_option_id"], ["modifier_options.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "modifier_option_id"),
    )
    for column in ("organization_id", "location_id", "modifier_option_id"):
        op.create_index(
            f"ix_modifier_option_location_settings_{column}",
            "modifier_option_location_settings",
            [column],
        )


def downgrade() -> None:
    op.drop_table("modifier_option_location_settings")
    op.drop_table("modifier_option_prices")
    op.drop_table("modifier_option_components")
    op.drop_table("modifier_options")
    op.drop_table("modifier_groups")
