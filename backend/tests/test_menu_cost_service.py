from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.menu.application.commands import RecipeComponentInput
from beanly.modules.menu.application.ports import (
    InventoryItemReference,
    WarehouseCostContext,
)
from beanly.modules.menu.application.services import MenuService
from beanly.modules.menu.domain.entities import (
    Product,
    ProductVariant,
    Recipe,
    RecipeComponent,
)
from beanly.modules.menu.domain.enums import ProductStatus
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import permissions_for


@pytest.mark.anyio
async def test_batch_cost_reads_inventory_costs_once_for_shared_components() -> None:
    now = datetime.now(UTC)
    organization_id = uuid4()
    location_id = uuid4()
    warehouse_id = uuid4()
    product_id = uuid4()
    item_id = uuid4()
    variants = tuple(
        ProductVariant(
            uuid4(),
            organization_id,
            product_id,
            name,
            None,
            price,
            index == 0,
            ProductStatus.ACTIVE,
            index,
            now,
            now,
        )
        for index, (name, price) in enumerate((("250 ml", 180000), ("350 ml", 200000)))
    )
    product = Product(
        product_id,
        organization_id,
        uuid4(),
        "Cappuccino",
        None,
        None,
        ProductStatus.ACTIVE,
        now,
        now,
        variants,
    )
    recipes = {
        variant.id: Recipe(
            (recipe_id := uuid4()),
            organization_id,
            variant.id,
            variant.name,
            Decimal(1),
            True,
            now,
            now,
            (
                RecipeComponent(
                    uuid4(),
                    recipe_id,
                    item_id,
                    Decimal(18 + index * 2),
                    0,
                    now,
                    now,
                ),
            ),
        )
        for index, variant in enumerate(variants)
    }

    class Repository:
        async def list_products(self, *args):
            return [product]

        async def list_recipes(self, organization_id_, variant_ids):
            assert organization_id_ == organization_id
            assert set(variant_ids) == {value.id for value in variants}
            return recipes

        async def get_effective_prices(self, organization_id_, variant_ids, location_id_):
            assert organization_id_ == organization_id
            assert location_id_ == location_id
            return {value.id: value.base_price_minor for value in variants}

    class Inventory:
        cost_calls = 0

        async def get_warehouse_context(self, organization_id_, warehouse_id_):
            assert organization_id_ == organization_id
            assert warehouse_id_ == warehouse_id
            return WarehouseCostContext(warehouse_id, location_id)

        async def get_items(self, organization_id_, item_ids):
            assert organization_id_ == organization_id
            return {item_id: InventoryItemReference(item_id, "Coffee", UnitCode.G)}

        async def get_current_costs(self, organization_id_, warehouse_id_, item_ids):
            self.cost_calls += 1
            assert item_ids == (item_id,)
            return {item_id: Decimal("8.5")}

    class Organizations:
        async def ensure_location_access(self, context, location_id_):
            assert context.organization_id == organization_id
            assert location_id_ == location_id

    inventory = Inventory()
    context = TenantContext(
        uuid4(),
        organization_id,
        uuid4(),
        MembershipRole.OWNER,
        permissions_for(MembershipRole.OWNER),
        LocationAccess.ALL,
    )
    results = await MenuService(Repository(), inventory, Organizations()).calculate_costs(
        context, warehouse_id
    )

    assert inventory.cost_calls == 1
    assert [value.recipe_cost for value in results] == [
        Decimal("153.000000"),
        Decimal("170.000000"),
    ]


@pytest.mark.anyio
async def test_recipe_service_rejects_nonpositive_quantity_before_persistence() -> None:
    now = datetime.now(UTC)
    organization_id = uuid4()
    variant = ProductVariant(
        uuid4(),
        organization_id,
        uuid4(),
        "Default",
        None,
        10000,
        True,
        ProductStatus.ACTIVE,
        0,
        now,
        now,
    )

    class Repository:
        async def get_variant(self, organization_id_, variant_id):
            return variant

    class MustNotCallInventory:
        async def get_items(self, *args):
            raise AssertionError("Validation must happen before inventory access")

    context = TenantContext(
        uuid4(),
        organization_id,
        uuid4(),
        MembershipRole.OWNER,
        permissions_for(MembershipRole.OWNER),
        LocationAccess.ALL,
    )
    service = MenuService(Repository(), MustNotCallInventory(), object())
    with pytest.raises(ValueError, match="positive"):
        await service.set_recipe(
            context,
            variant.id,
            None,
            Decimal(1),
            (RecipeComponentInput(uuid4(), Decimal("-1"), UnitCode.G, 0),),
        )
