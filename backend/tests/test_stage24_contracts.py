from pathlib import Path

import pytest

from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for
from beanly.modules.promotions.api.schemas import PromotionWrite

PROMOTIONS = Path("beanly/modules/promotions")


def test_stage24_role_permissions_match_the_discount_boundary() -> None:
    read = Permission.PROMOTIONS_READ
    write = Permission.PROMOTIONS_WRITE
    apply = Permission.DISCOUNTS_APPLY
    override = Permission.DISCOUNTS_OVERRIDE

    assert {read, write, apply, override} <= permissions_for(MembershipRole.OWNER)
    assert {read, write, apply, override} <= permissions_for(MembershipRole.ADMIN)
    assert {read, apply, override} <= permissions_for(MembershipRole.MANAGER)
    assert write not in permissions_for(MembershipRole.MANAGER)
    assert permissions_for(MembershipRole.ACCOUNTANT) & {read, write, apply, override} == {
        read
    }
    assert permissions_for(MembershipRole.CASHIER) & {read, write, apply, override} == {
        apply
    }
    assert not permissions_for(MembershipRole.BARISTA) & {read, write, apply, override}


@pytest.mark.parametrize(
    "change",
    [
        {"percent_rate": None},
        {"percent_rate": "100.0001"},
        {"all_locations": False, "location_ids": []},
        {
            "targets": [
                {
                    "role": "ELIGIBLE",
                    "target_type": "ALL",
                    "target_id": "00000000-0000-0000-0000-000000000001",
                }
            ]
        },
        {
            "schedules": [
                {"weekday": 0, "start_local_time": "17:00", "end_local_time": "15:00"}
            ]
        },
    ],
)
def test_promotion_schema_rejects_invalid_money_target_location_and_schedule(
    change: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "name": "Happy Hour",
        "pos_name": "Happy Hour",
        "application_mode": "AUTOMATIC",
        "discount_kind": "PERCENT",
        "scope": "ITEM",
        "percent_rate": "20.0000",
    }
    payload.update(change)

    with pytest.raises(ValueError):
        PromotionWrite.model_validate(payload)


def test_promotions_domain_is_framework_free_and_pricing_does_not_touch_database() -> None:
    for path in (PROMOTIONS / "domain").rglob("*.py"):
        source = path.read_text(encoding="utf-8").casefold()
        assert "fastapi" not in source, path
        assert "sqlalchemy" not in source, path
        assert "infrastructure" not in source, path

    pricing = (PROMOTIONS / "application/pricing_engine.py").read_text(encoding="utf-8").casefold()
    assert "sqlalchemy" not in pricing
    assert "infrastructure" not in pricing
    assert "fastapi" not in pricing


def test_stage24_migration_is_stacked_and_declares_the_exact_owned_tables() -> None:
    source = Path("migrations/versions/0024_promotions_pricing.py").read_text(encoding="utf-8")
    assert 'revision = "0024_promotions_pricing"' in source
    assert 'down_revision = "0023_onboarding_imports"' in source
    expected = {
        "promotions",
        "promotion_locations",
        "promotion_schedules",
        "promotion_targets",
        "promotion_codes",
        "sales_order_discounts",
        "sales_order_discount_allocations",
        "refund_discount_allocations",
        "analytics_promotions_daily",
    }
    assert {name for name in expected if f'"{name}"' in source} == expected
