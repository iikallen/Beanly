from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MenuCategoryModel(Base):
    __tablename__ = "menu_categories"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProductModel(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')", name="ck_product_status"),
        Index("ix_products_organization_name", "organization_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    category_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("menu_categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    variants: Mapped[list["ProductVariantModel"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductVariantModel(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("base_price_minor >= 0", name="ck_variant_base_price"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')", name="ck_variant_status"),
        Index(
            "uq_product_variants_organization_sku",
            "organization_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
            sqlite_where=text("sku IS NOT NULL"),
        ),
        Index(
            "uq_product_variants_active_default",
            "product_id",
            unique=True,
            postgresql_where=text("is_default AND status <> 'ARCHIVED'"),
            sqlite_where=text("is_default = 1 AND status <> 'ARCHIVED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    base_price_minor: Mapped[int] = mapped_column(BigInteger)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    product: Mapped[ProductModel] = relationship(back_populates="variants")
    recipe: Mapped["RecipeModel | None"] = relationship(
        back_populates="variant", cascade="all, delete-orphan", uselist=False
    )
    modifier_groups: Mapped[list["ModifierGroupModel"]] = relationship(
        back_populates="variant", cascade="all, delete-orphan"
    )


class VariantPriceModel(Base):
    __tablename__ = "variant_prices"
    __table_args__ = (
        UniqueConstraint("location_id", "product_variant_id"),
        CheckConstraint("price_minor >= 0", name="ck_variant_price_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    product_variant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    price_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProductLocationSettingModel(Base):
    __tablename__ = "product_location_settings"
    __table_args__ = (UniqueConstraint("location_id", "product_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    product_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class RecipeModel(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint("product_variant_id"),
        CheckConstraint("yield_quantity > 0", name="ck_recipe_yield_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    product_variant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    yield_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    variant: Mapped[ProductVariantModel] = relationship(back_populates="recipe")
    components: Mapped[list["RecipeComponentModel"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )


class RecipeComponentModel(Base):
    __tablename__ = "recipe_components"
    __table_args__ = (
        UniqueConstraint("recipe_id", "inventory_item_id"),
        CheckConstraint("quantity > 0", name="ck_recipe_component_quantity_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    recipe_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("recipes.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    recipe: Mapped[RecipeModel] = relationship(back_populates="components")


class ModifierGroupModel(Base):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        CheckConstraint(
            "selection_type IN ('SINGLE', 'MULTIPLE')", name="ck_modifier_group_selection_type"
        ),
        CheckConstraint("min_selections >= 0", name="ck_modifier_group_min_nonnegative"),
        CheckConstraint("max_selections >= 1", name="ck_modifier_group_max_positive"),
        CheckConstraint("min_selections <= max_selections", name="ck_modifier_group_min_max"),
        CheckConstraint(
            "selection_type <> 'SINGLE' OR max_selections = 1",
            name="ck_modifier_group_single_max",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    product_variant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    selection_type: Mapped[str] = mapped_column(String(16))
    min_selections: Mapped[int] = mapped_column()
    max_selections: Mapped[int] = mapped_column()
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    variant: Mapped[ProductVariantModel] = relationship(back_populates="modifier_groups")
    options: Mapped[list["ModifierOptionModel"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class ModifierOptionModel(Base):
    __tablename__ = "modifier_options"
    __table_args__ = (
        CheckConstraint("base_price_delta_minor >= 0", name="ck_modifier_option_price_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    modifier_group_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("modifier_groups.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    base_price_delta_minor: Mapped[int] = mapped_column(BigInteger)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    group: Mapped[ModifierGroupModel] = relationship(back_populates="options")
    components: Mapped[list["ModifierOptionComponentModel"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )
    prices: Mapped[list["ModifierOptionPriceModel"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )
    location_settings: Mapped[list["ModifierOptionLocationSettingModel"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )


class ModifierOptionComponentModel(Base):
    __tablename__ = "modifier_option_components"
    __table_args__ = (
        UniqueConstraint("modifier_option_id", "inventory_item_id"),
        CheckConstraint("quantity_delta <> 0", name="ck_modifier_component_quantity_nonzero"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    modifier_option_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("modifier_options.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    option: Mapped[ModifierOptionModel] = relationship(back_populates="components")


class ModifierOptionPriceModel(Base):
    __tablename__ = "modifier_option_prices"
    __table_args__ = (
        UniqueConstraint("location_id", "modifier_option_id"),
        CheckConstraint("price_delta_minor >= 0", name="ck_modifier_price_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    modifier_option_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("modifier_options.id", ondelete="CASCADE"), index=True
    )
    price_delta_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    option: Mapped[ModifierOptionModel] = relationship(back_populates="prices")


class ModifierOptionLocationSettingModel(Base):
    __tablename__ = "modifier_option_location_settings"
    __table_args__ = (UniqueConstraint("location_id", "modifier_option_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    modifier_option_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("modifier_options.id", ondelete="CASCADE"), index=True
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    option: Mapped[ModifierOptionModel] = relationship(back_populates="location_settings")
