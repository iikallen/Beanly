from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.menu.domain.entities import (
    Category,
    Product,
    ProductLocationSetting,
    ProductVariant,
    Recipe,
    VariantPrice,
)
from beanly.modules.menu.domain.enums import ProductStatus
from beanly.modules.menu.domain.exceptions import InvalidMenuOperation
from beanly.modules.menu.infrastructure.db.mappers import (
    to_category,
    to_product,
    to_product_location,
    to_recipe,
    to_variant,
    to_variant_price,
)
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ProductLocationSettingModel,
    ProductModel,
    ProductVariantModel,
    RecipeComponentModel,
    RecipeModel,
    VariantPriceModel,
)


class SqlAlchemyMenuRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_category(self, value: Category) -> Category:
        model = MenuCategoryModel(**_category_values(value))
        self.session.add(model)
        await self.session.flush()
        return to_category(model)

    async def get_category(self, organization_id: UUID, category_id: UUID) -> Category | None:
        model = await self.session.scalar(
            select(MenuCategoryModel).where(
                MenuCategoryModel.organization_id == organization_id,
                MenuCategoryModel.id == category_id,
            )
        )
        return to_category(model) if model else None

    async def lock_category(self, organization_id: UUID, category_id: UUID) -> bool:
        value = await self.session.scalar(
            select(MenuCategoryModel.id)
            .where(
                MenuCategoryModel.organization_id == organization_id,
                MenuCategoryModel.id == category_id,
            )
            .with_for_update()
        )
        return value is not None

    async def list_categories(self, organization_id: UUID) -> list[Category]:
        models = await self.session.scalars(
            select(MenuCategoryModel)
            .where(MenuCategoryModel.organization_id == organization_id)
            .order_by(MenuCategoryModel.sort_order, MenuCategoryModel.name, MenuCategoryModel.id)
        )
        return [to_category(model) for model in models]

    async def update_category(self, value: Category) -> Category:
        await self.session.execute(
            update(MenuCategoryModel)
            .where(
                MenuCategoryModel.organization_id == value.organization_id,
                MenuCategoryModel.id == value.id,
            )
            .values(**_category_values(value))
        )
        await self.session.flush()
        return value

    async def add_product(self, value: Product) -> Product:
        model = ProductModel(**_product_values(value))
        self.session.add(model)
        await self.session.flush()
        return await self._product(value.organization_id, value.id)

    async def get_product(self, organization_id: UUID, product_id: UUID) -> Product | None:
        return await self._product(organization_id, product_id)

    async def lock_product(self, organization_id: UUID, product_id: UUID) -> ProductStatus | None:
        value = await self.session.scalar(
            select(ProductModel.status)
            .where(
                ProductModel.organization_id == organization_id,
                ProductModel.id == product_id,
            )
            .with_for_update()
        )
        return ProductStatus(value) if value is not None else None

    async def list_products(
        self,
        organization_id: UUID,
        category_id: UUID | None,
        status: ProductStatus | None,
        search: str | None,
        location_id: UUID | None,
    ) -> list[Product]:
        statement = select(ProductModel).where(ProductModel.organization_id == organization_id)
        if category_id is not None:
            statement = statement.where(ProductModel.category_id == category_id)
        if status is not None:
            statement = statement.where(ProductModel.status == status.value)
        if search:
            statement = statement.where(ProductModel.name.ilike(f"%{search}%"))
        if status == ProductStatus.ACTIVE:
            statement = statement.join(
                MenuCategoryModel, MenuCategoryModel.id == ProductModel.category_id
            ).where(MenuCategoryModel.is_active.is_(True))
        if location_id is not None:
            row_statement = statement.outerjoin(
                ProductLocationSettingModel,
                and_(
                    ProductLocationSettingModel.product_id == ProductModel.id,
                    ProductLocationSettingModel.location_id == location_id,
                    ProductLocationSettingModel.organization_id == organization_id,
                ),
            ).add_columns(
                func.coalesce(ProductLocationSettingModel.is_available, True),
                func.coalesce(ProductLocationSettingModel.is_visible, True),
            )
            row_statement = row_statement.options(selectinload(ProductModel.variants)).order_by(
                ProductModel.name, ProductModel.id
            )
            rows = (await self.session.execute(row_statement)).all()
            return [
                replace(
                    to_product(model),
                    is_available=is_available,
                    is_visible=is_visible,
                )
                for model, is_available, is_visible in rows
            ]
        statement = statement.options(selectinload(ProductModel.variants)).order_by(
            ProductModel.name, ProductModel.id
        )
        return [to_product(model) for model in await self.session.scalars(statement)]

    async def update_product(self, value: Product) -> Product:
        await self.session.execute(
            update(ProductModel)
            .where(
                ProductModel.organization_id == value.organization_id,
                ProductModel.id == value.id,
            )
            .values(**_product_values(value))
        )
        await self.session.flush()
        return await self._product(value.organization_id, value.id)

    async def add_variant(self, value: ProductVariant) -> ProductVariant:
        model = ProductVariantModel(**_variant_values(value))
        self.session.add(model)
        await self.session.flush()
        return to_variant(model)

    async def get_variant(self, organization_id: UUID, variant_id: UUID) -> ProductVariant | None:
        model = await self.session.scalar(
            select(ProductVariantModel).where(
                ProductVariantModel.organization_id == organization_id,
                ProductVariantModel.id == variant_id,
            )
        )
        return to_variant(model) if model else None

    async def update_variant(self, value: ProductVariant) -> ProductVariant:
        await self.session.execute(
            update(ProductVariantModel)
            .where(
                ProductVariantModel.organization_id == value.organization_id,
                ProductVariantModel.id == value.id,
            )
            .values(**_variant_values(value))
        )
        await self.session.flush()
        return value

    async def clear_default_variant(self, organization_id: UUID, product_id: UUID) -> None:
        await self.session.execute(
            update(ProductVariantModel)
            .where(
                ProductVariantModel.organization_id == organization_id,
                ProductVariantModel.product_id == product_id,
                ProductVariantModel.status != ProductStatus.ARCHIVED.value,
                ProductVariantModel.is_default.is_(True),
            )
            .values(is_default=False, updated_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def first_active_variant(
        self, organization_id: UUID, product_id: UUID, exclude_id: UUID
    ) -> ProductVariant | None:
        model = await self.session.scalar(
            select(ProductVariantModel)
            .where(
                ProductVariantModel.organization_id == organization_id,
                ProductVariantModel.product_id == product_id,
                ProductVariantModel.id != exclude_id,
                ProductVariantModel.status != ProductStatus.ARCHIVED.value,
            )
            .order_by(ProductVariantModel.sort_order, ProductVariantModel.id)
        )
        return to_variant(model) if model else None

    async def get_recipe(self, organization_id: UUID, variant_id: UUID) -> Recipe | None:
        model = await self.session.scalar(_recipe_query(organization_id, variant_id))
        return to_recipe(model) if model else None

    async def list_recipes(
        self, organization_id: UUID, variant_ids: tuple[UUID, ...]
    ) -> dict[UUID, Recipe]:
        if not variant_ids:
            return {}
        models = await self.session.scalars(
            select(RecipeModel)
            .where(
                RecipeModel.organization_id == organization_id,
                RecipeModel.product_variant_id.in_(variant_ids),
                RecipeModel.is_active.is_(True),
            )
            .options(selectinload(RecipeModel.components))
        )
        values = [to_recipe(model) for model in models]
        return {value.product_variant_id: value for value in values}

    async def replace_recipe(self, value: Recipe) -> tuple[Recipe, bool]:
        # Serialize whole-document recipe PUTs for one variant.
        variant = await self.session.scalar(
            select(ProductVariantModel)
            .where(
                ProductVariantModel.organization_id == value.organization_id,
                ProductVariantModel.id == value.product_variant_id,
            )
            .with_for_update()
        )
        if variant is None:
            raise LookupError("Variant disappeared while replacing recipe")
        if variant.status == ProductStatus.ARCHIVED.value:
            raise InvalidMenuOperation("Cannot set a recipe on an archived variant")
        current = await self.session.scalar(
            select(RecipeModel)
            .where(
                RecipeModel.organization_id == value.organization_id,
                RecipeModel.product_variant_id == value.product_variant_id,
            )
            .with_for_update()
        )
        created = current is None
        if current is None:
            current = RecipeModel(
                id=value.id,
                organization_id=value.organization_id,
                product_variant_id=value.product_variant_id,
                name=value.name,
                yield_quantity=value.yield_quantity,
                is_active=value.is_active,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
            self.session.add(current)
            await self.session.flush()
        else:
            current.name = value.name
            current.yield_quantity = value.yield_quantity
            current.is_active = value.is_active
            current.updated_at = value.updated_at
            await self.session.execute(
                RecipeComponentModel.__table__.delete().where(
                    RecipeComponentModel.recipe_id == current.id
                )
            )
        self.session.add_all(
            RecipeComponentModel(
                id=component.id,
                recipe_id=current.id,
                inventory_item_id=component.inventory_item_id,
                quantity=component.quantity,
                sort_order=component.sort_order,
                created_at=component.created_at,
                updated_at=component.updated_at,
            )
            for component in value.components
        )
        await self.session.flush()
        return (
            to_recipe(
                await self.session.scalar(
                    _recipe_query(value.organization_id, value.product_variant_id)
                )
            ),
            created,
        )

    async def set_variant_price(self, value: VariantPrice) -> VariantPrice:
        insert = _insert_for(self.session, VariantPriceModel).values(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            product_variant_id=value.product_variant_id,
            price_minor=value.price_minor,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
        statement = insert.on_conflict_do_update(
            index_elements=["location_id", "product_variant_id"],
            set_={"price_minor": value.price_minor, "updated_at": value.updated_at},
        ).returning(VariantPriceModel)
        model = (await self.session.scalars(statement)).one()
        return to_variant_price(model)

    async def delete_variant_price(
        self, organization_id: UUID, variant_id: UUID, location_id: UUID
    ) -> None:
        await self.session.execute(
            VariantPriceModel.__table__.delete().where(
                VariantPriceModel.organization_id == organization_id,
                VariantPriceModel.product_variant_id == variant_id,
                VariantPriceModel.location_id == location_id,
            )
        )
        await self.session.flush()

    async def get_effective_price(
        self, organization_id: UUID, variant_id: UUID, location_id: UUID | None
    ) -> int | None:
        statement = select(ProductVariantModel.base_price_minor).where(
            ProductVariantModel.organization_id == organization_id,
            ProductVariantModel.id == variant_id,
        )
        if location_id is not None:
            statement = (
                select(
                    func.coalesce(
                        VariantPriceModel.price_minor, ProductVariantModel.base_price_minor
                    )
                )
                .select_from(ProductVariantModel)
                .outerjoin(
                    VariantPriceModel,
                    and_(
                        VariantPriceModel.product_variant_id == ProductVariantModel.id,
                        VariantPriceModel.location_id == location_id,
                        VariantPriceModel.organization_id == organization_id,
                    ),
                )
                .where(
                    ProductVariantModel.organization_id == organization_id,
                    ProductVariantModel.id == variant_id,
                )
            )
        return await self.session.scalar(statement)

    async def get_effective_prices(
        self, organization_id: UUID, variant_ids: tuple[UUID, ...], location_id: UUID
    ) -> dict[UUID, int]:
        if not variant_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    ProductVariantModel.id,
                    func.coalesce(
                        VariantPriceModel.price_minor,
                        ProductVariantModel.base_price_minor,
                    ),
                )
                .outerjoin(
                    VariantPriceModel,
                    and_(
                        VariantPriceModel.product_variant_id == ProductVariantModel.id,
                        VariantPriceModel.location_id == location_id,
                        VariantPriceModel.organization_id == organization_id,
                    ),
                )
                .where(
                    ProductVariantModel.organization_id == organization_id,
                    ProductVariantModel.id.in_(variant_ids),
                )
            )
        ).all()
        return dict(rows)

    async def get_location_prices(
        self, organization_id: UUID, variant_ids: tuple[UUID, ...], location_id: UUID
    ) -> dict[UUID, int]:
        if not variant_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    VariantPriceModel.product_variant_id,
                    VariantPriceModel.price_minor,
                ).where(
                    VariantPriceModel.organization_id == organization_id,
                    VariantPriceModel.location_id == location_id,
                    VariantPriceModel.product_variant_id.in_(variant_ids),
                )
            )
        ).all()
        return dict(rows)

    async def set_product_location(self, value: ProductLocationSetting) -> ProductLocationSetting:
        insert = _insert_for(self.session, ProductLocationSettingModel).values(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            product_id=value.product_id,
            is_available=value.is_available,
            is_visible=value.is_visible,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
        statement = insert.on_conflict_do_update(
            index_elements=["location_id", "product_id"],
            set_={
                "is_available": value.is_available,
                "is_visible": value.is_visible,
                "updated_at": value.updated_at,
            },
        ).returning(ProductLocationSettingModel)
        model = (await self.session.scalars(statement)).one()
        return to_product_location(model)

    async def get_product_location(
        self, organization_id: UUID, product_id: UUID, location_id: UUID
    ) -> ProductLocationSetting | None:
        model = await self.session.scalar(
            select(ProductLocationSettingModel).where(
                ProductLocationSettingModel.organization_id == organization_id,
                ProductLocationSettingModel.product_id == product_id,
                ProductLocationSettingModel.location_id == location_id,
            )
        )
        return to_product_location(model) if model else None

    async def _product(self, organization_id: UUID, product_id: UUID) -> Product | None:
        model = await self.session.scalar(
            select(ProductModel)
            .where(
                ProductModel.organization_id == organization_id,
                ProductModel.id == product_id,
            )
            .options(selectinload(ProductModel.variants))
        )
        return to_product(model) if model else None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _category_values(value: Category) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "name": value.name,
        "sort_order": value.sort_order,
        "is_active": value.is_active,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _product_values(value: Product) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "category_id": value.category_id,
        "name": value.name,
        "description": value.description,
        "image_url": value.image_url,
        "status": value.status.value,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _variant_values(value: ProductVariant) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "product_id": value.product_id,
        "name": value.name,
        "sku": value.sku,
        "base_price_minor": value.base_price_minor,
        "is_default": value.is_default,
        "status": value.status.value,
        "sort_order": value.sort_order,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _recipe_query(organization_id: UUID, variant_id: UUID):
    return (
        select(RecipeModel)
        .where(
            RecipeModel.organization_id == organization_id,
            RecipeModel.product_variant_id == variant_id,
        )
        .options(selectinload(RecipeModel.components))
    )


def _insert_for(session: AsyncSession, model):
    return (
        postgresql_insert(model)
        if session.get_bind().dialect.name == "postgresql"
        else sqlite_insert(model)
    )
