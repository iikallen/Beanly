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
    ModifierGroup,
    ModifierOption,
    ModifierOptionLocationSetting,
    ModifierOptionPrice,
    Product,
    ProductLocationSetting,
    ProductVariant,
    Recipe,
    VariantPrice,
)
from beanly.modules.menu.domain.enums import ProductStatus
from beanly.modules.menu.domain.exceptions import InvalidMenuOperation, MenuConflict
from beanly.modules.menu.infrastructure.db.mappers import (
    to_category,
    to_modifier_group,
    to_modifier_location_setting,
    to_modifier_option,
    to_modifier_option_price,
    to_product,
    to_product_location,
    to_recipe,
    to_variant,
    to_variant_price,
)
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ModifierGroupModel,
    ModifierOptionComponentModel,
    ModifierOptionLocationSettingModel,
    ModifierOptionModel,
    ModifierOptionPriceModel,
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
            row_statement = row_statement.options(*_product_load_options()).order_by(
                ProductModel.name, ProductModel.id
            )
            rows = (await self.session.execute(row_statement)).all()
            return [
                replace(
                    to_product(model, location_id),
                    is_available=is_available,
                    is_visible=is_visible,
                )
                for model, is_available, is_visible in rows
            ]
        statement = statement.options(*_product_load_options()).order_by(
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

    async def add_modifier_group(self, value: ModifierGroup) -> ModifierGroup:
        variant_status = await self.session.scalar(
            select(ProductVariantModel.status)
            .where(
                ProductVariantModel.organization_id == value.organization_id,
                ProductVariantModel.id == value.product_variant_id,
            )
            .with_for_update()
        )
        if variant_status is None:
            raise LookupError("Variant disappeared while creating modifier group")
        if variant_status == ProductStatus.ARCHIVED.value:
            raise InvalidMenuOperation("Cannot add modifiers to an archived variant")
        model = ModifierGroupModel(**_modifier_group_values(value))
        self.session.add(model)
        await self.session.flush()
        return to_modifier_group(model)

    async def get_modifier_group(
        self, organization_id: UUID, group_id: UUID, location_id: UUID | None = None
    ) -> ModifierGroup | None:
        model = await self.session.scalar(_modifier_group_query(organization_id, group_id))
        return to_modifier_group(model, location_id) if model else None

    async def list_modifier_groups(
        self,
        organization_id: UUID,
        variant_id: UUID,
        location_id: UUID | None = None,
        active_only: bool = False,
    ) -> list[ModifierGroup]:
        statement = select(ModifierGroupModel).where(
            ModifierGroupModel.organization_id == organization_id,
            ModifierGroupModel.product_variant_id == variant_id,
        )
        if active_only:
            statement = statement.where(ModifierGroupModel.is_active.is_(True))
        models = await self.session.scalars(
            statement.options(*_modifier_load_options()).order_by(
                ModifierGroupModel.sort_order, ModifierGroupModel.id
            )
        )
        return [to_modifier_group(model, location_id) for model in models]

    async def update_modifier_group(self, value: ModifierGroup) -> ModifierGroup:
        current = await self._lock_modifier_group(value.organization_id, value.id)
        if not current.is_active:
            raise InvalidMenuOperation("Archived modifier groups cannot be updated")
        active_defaults = await self.session.scalar(
            select(func.count())
            .select_from(ModifierOptionModel)
            .where(
                ModifierOptionModel.organization_id == value.organization_id,
                ModifierOptionModel.modifier_group_id == value.id,
                ModifierOptionModel.is_active.is_(True),
                ModifierOptionModel.is_default.is_(True),
            )
        )
        if active_defaults > value.max_selections:
            raise MenuConflict("Default options exceed max selections")
        result = await self.session.execute(
            update(ModifierGroupModel)
            .where(
                ModifierGroupModel.organization_id == value.organization_id,
                ModifierGroupModel.id == value.id,
            )
            .values(**_modifier_group_values(value))
        )
        if result.rowcount != 1:
            raise LookupError("Modifier group disappeared while updating")
        await self.session.flush()
        return value

    async def add_modifier_option(self, value: ModifierOption) -> ModifierOption:
        group = await self._lock_modifier_group(value.organization_id, value.modifier_group_id)
        if not group.is_active:
            raise InvalidMenuOperation("Cannot add options to an archived modifier group")
        if value.is_default:
            active_defaults = await self.session.scalar(
                select(func.count())
                .select_from(ModifierOptionModel)
                .where(
                    ModifierOptionModel.organization_id == value.organization_id,
                    ModifierOptionModel.modifier_group_id == value.modifier_group_id,
                    ModifierOptionModel.is_active.is_(True),
                    ModifierOptionModel.is_default.is_(True),
                )
            )
            if active_defaults >= group.max_selections:
                raise MenuConflict("Default options exceed max selections")
        model = ModifierOptionModel(**_modifier_option_values(value))
        self.session.add(model)
        await self.session.flush()
        return to_modifier_option(model)

    async def get_modifier_option(
        self, organization_id: UUID, option_id: UUID, location_id: UUID | None = None
    ) -> ModifierOption | None:
        model = await self.session.scalar(
            select(ModifierOptionModel)
            .where(
                ModifierOptionModel.organization_id == organization_id,
                ModifierOptionModel.id == option_id,
            )
            .options(
                selectinload(ModifierOptionModel.components),
                selectinload(ModifierOptionModel.prices),
                selectinload(ModifierOptionModel.location_settings),
            )
            .execution_options(populate_existing=True)
        )
        return to_modifier_option(model, location_id) if model else None

    async def update_modifier_option(self, value: ModifierOption) -> ModifierOption:
        current = await self.session.scalar(
            select(ModifierOptionModel)
            .where(
                ModifierOptionModel.organization_id == value.organization_id,
                ModifierOptionModel.id == value.id,
            )
            .with_for_update()
        )
        if current is None:
            raise LookupError("Modifier option disappeared while updating")
        if not current.is_active:
            raise InvalidMenuOperation("Archived modifier options cannot be updated")
        group = await self._lock_modifier_group(value.organization_id, current.modifier_group_id)
        if not group.is_active:
            raise InvalidMenuOperation("Archived modifier groups cannot be updated")
        if value.is_default:
            active_defaults = await self.session.scalar(
                select(func.count())
                .select_from(ModifierOptionModel)
                .where(
                    ModifierOptionModel.organization_id == value.organization_id,
                    ModifierOptionModel.modifier_group_id == current.modifier_group_id,
                    ModifierOptionModel.id != value.id,
                    ModifierOptionModel.is_active.is_(True),
                    ModifierOptionModel.is_default.is_(True),
                )
            )
            if active_defaults >= group.max_selections:
                raise MenuConflict("Default options exceed max selections")
        result = await self.session.execute(
            update(ModifierOptionModel)
            .where(
                ModifierOptionModel.organization_id == value.organization_id,
                ModifierOptionModel.id == value.id,
            )
            .values(**_modifier_option_values(value))
        )
        if result.rowcount != 1:
            raise LookupError("Modifier option disappeared while updating")
        await self.session.flush()
        return value

    async def replace_modifier_components(self, value: ModifierOption) -> ModifierOption:
        option = await self.session.scalar(
            select(ModifierOptionModel)
            .where(
                ModifierOptionModel.organization_id == value.organization_id,
                ModifierOptionModel.id == value.id,
            )
            .with_for_update()
        )
        if option is None:
            raise LookupError("Modifier option disappeared while replacing components")
        if not option.is_active:
            raise InvalidMenuOperation("Archived modifier options cannot be updated")
        group = await self._lock_modifier_group(value.organization_id, option.modifier_group_id)
        if not group.is_active:
            raise InvalidMenuOperation("Archived modifier groups cannot be updated")
        await self.session.execute(
            ModifierOptionComponentModel.__table__.delete().where(
                ModifierOptionComponentModel.modifier_option_id == value.id
            )
        )
        self.session.add_all(
            ModifierOptionComponentModel(
                id=component.id,
                modifier_option_id=value.id,
                inventory_item_id=component.inventory_item_id,
                quantity_delta=component.quantity_delta,
                sort_order=component.sort_order,
                created_at=component.created_at,
                updated_at=component.updated_at,
            )
            for component in value.components
        )
        await self.session.flush()
        saved = await self.get_modifier_option(value.organization_id, value.id)
        if saved is None:
            raise LookupError("Modifier option disappeared while replacing components")
        return saved

    async def set_modifier_option_price(self, value: ModifierOptionPrice) -> ModifierOptionPrice:
        await self._lock_editable_modifier_option(value.organization_id, value.modifier_option_id)
        insert = _insert_for(self.session, ModifierOptionPriceModel).values(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            modifier_option_id=value.modifier_option_id,
            price_delta_minor=value.price_delta_minor,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
        model = (
            await self.session.scalars(
                insert.on_conflict_do_update(
                    index_elements=["location_id", "modifier_option_id"],
                    set_={
                        "price_delta_minor": value.price_delta_minor,
                        "updated_at": value.updated_at,
                    },
                ).returning(ModifierOptionPriceModel)
            )
        ).one()
        return to_modifier_option_price(model)

    async def delete_modifier_option_price(
        self, organization_id: UUID, option_id: UUID, location_id: UUID
    ) -> None:
        await self._lock_editable_modifier_option(organization_id, option_id)
        await self.session.execute(
            ModifierOptionPriceModel.__table__.delete().where(
                ModifierOptionPriceModel.organization_id == organization_id,
                ModifierOptionPriceModel.modifier_option_id == option_id,
                ModifierOptionPriceModel.location_id == location_id,
            )
        )
        await self.session.flush()

    async def set_modifier_option_location(
        self, value: ModifierOptionLocationSetting
    ) -> ModifierOptionLocationSetting:
        await self._lock_editable_modifier_option(value.organization_id, value.modifier_option_id)
        insert = _insert_for(self.session, ModifierOptionLocationSettingModel).values(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            modifier_option_id=value.modifier_option_id,
            is_available=value.is_available,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
        model = (
            await self.session.scalars(
                insert.on_conflict_do_update(
                    index_elements=["location_id", "modifier_option_id"],
                    set_={"is_available": value.is_available, "updated_at": value.updated_at},
                ).returning(ModifierOptionLocationSettingModel)
            )
        ).one()
        return to_modifier_location_setting(model)

    async def _product(self, organization_id: UUID, product_id: UUID) -> Product | None:
        model = await self.session.scalar(
            select(ProductModel)
            .where(
                ProductModel.organization_id == organization_id,
                ProductModel.id == product_id,
            )
            .options(*_product_load_options())
        )
        return to_product(model) if model else None

    async def _lock_modifier_group(
        self, organization_id: UUID, group_id: UUID
    ) -> ModifierGroupModel:
        model = await self.session.scalar(
            select(ModifierGroupModel)
            .where(
                ModifierGroupModel.organization_id == organization_id,
                ModifierGroupModel.id == group_id,
            )
            .with_for_update()
        )
        if model is None:
            raise LookupError("Modifier group disappeared")
        return model

    async def _lock_editable_modifier_option(
        self, organization_id: UUID, option_id: UUID
    ) -> ModifierOptionModel:
        model = await self.session.scalar(
            select(ModifierOptionModel)
            .where(
                ModifierOptionModel.organization_id == organization_id,
                ModifierOptionModel.id == option_id,
            )
            .with_for_update()
        )
        if model is None:
            raise LookupError("Modifier option disappeared")
        if not model.is_active:
            raise InvalidMenuOperation("Archived modifier options cannot be updated")
        group = await self._lock_modifier_group(organization_id, model.modifier_group_id)
        if not group.is_active:
            raise InvalidMenuOperation("Archived modifier groups cannot be updated")
        return model

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


def _modifier_group_values(value: ModifierGroup) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "product_variant_id": value.product_variant_id,
        "name": value.name,
        "selection_type": value.selection_type.value,
        "min_selections": value.min_selections,
        "max_selections": value.max_selections,
        "sort_order": value.sort_order,
        "is_active": value.is_active,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _modifier_option_values(value: ModifierOption) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "modifier_group_id": value.modifier_group_id,
        "name": value.name,
        "base_price_delta_minor": value.base_price_delta_minor,
        "is_default": value.is_default,
        "sort_order": value.sort_order,
        "is_active": value.is_active,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _modifier_load_options():
    return (
        selectinload(ModifierGroupModel.options).selectinload(ModifierOptionModel.components),
        selectinload(ModifierGroupModel.options).selectinload(ModifierOptionModel.prices),
        selectinload(ModifierGroupModel.options).selectinload(
            ModifierOptionModel.location_settings
        ),
    )


def _modifier_group_query(organization_id: UUID, group_id: UUID):
    return (
        select(ModifierGroupModel)
        .where(
            ModifierGroupModel.organization_id == organization_id,
            ModifierGroupModel.id == group_id,
        )
        .options(*_modifier_load_options())
        .execution_options(populate_existing=True)
    )


def _product_load_options():
    groups = selectinload(ProductModel.variants).selectinload(ProductVariantModel.modifier_groups)
    return (
        selectinload(ProductModel.variants),
        groups.selectinload(ModifierGroupModel.options).selectinload(ModifierOptionModel.prices),
        groups.selectinload(ModifierGroupModel.options).selectinload(
            ModifierOptionModel.location_settings
        ),
    )


def _insert_for(session: AsyncSession, model):
    return (
        postgresql_insert(model)
        if session.get_bind().dialect.name == "postgresql"
        else sqlite_insert(model)
    )
