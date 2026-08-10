from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update

from beanly.modules.inventory.infrastructure.db.models import (
    InventoryItemModel,
    StockBalanceModel,
)
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)


@pytest.mark.anyio
async def test_negative_stock_is_net_per_item_and_location_across_warehouses(
    app_client,
) -> None:
    _, sessions = app_client
    organization_id = uuid4()
    location_id = uuid4()
    item_id = uuid4()
    positive_balance_id = uuid4()

    async with sessions() as session:
        session.add(
            InventoryItemModel(
                id=item_id,
                organization_id=organization_id,
                name="Coffee",
                base_unit="g",
            )
        )
        session.add_all(
            (
                StockBalanceModel(
                    id=uuid4(),
                    organization_id=organization_id,
                    location_id=location_id,
                    warehouse_id=uuid4(),
                    inventory_item_id=item_id,
                    quantity=Decimal("-5"),
                    average_unit_cost=Decimal("2"),
                ),
                StockBalanceModel(
                    id=positive_balance_id,
                    organization_id=organization_id,
                    location_id=location_id,
                    warehouse_id=uuid4(),
                    inventory_item_id=item_id,
                    quantity=Decimal("7"),
                    average_unit_cost=Decimal("3"),
                ),
            )
        )
        await session.commit()
        repository = SqlAlchemyInventoryRepository(session)

        health = await repository.dashboard_inventory_health(
            organization_id, (location_id,)
        )
        negative = await repository.dashboard_negative_items(
            organization_id, (location_id,), 5
        )
        assert health[1] == 0
        assert negative == ()

        await session.execute(
            update(StockBalanceModel)
            .where(StockBalanceModel.id == positive_balance_id)
            .values(quantity=Decimal("2"))
        )
        await session.commit()

        health = await repository.dashboard_inventory_health(
            organization_id, (location_id,)
        )
        negative = await repository.dashboard_negative_items(
            organization_id, (location_id,), 5
        )
        assert health[1] == 1
        assert len(negative) == 1
        assert negative[0][:3] == (item_id, location_id, "Coffee")
        assert negative[0][3:] == (Decimal("-3"), "g")
