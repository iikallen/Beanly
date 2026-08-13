from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from beanly.modules.promotions.application.pricing_engine import (
    largest_remainder_allocate,
    price_order,
)
from beanly.modules.promotions.domain.entities import (
    PricingItem,
    Promotion,
    PromotionSchedule,
    PromotionTarget,
)
from beanly.modules.promotions.domain.enums import (
    ApplicationMode,
    DiscountKind,
    PromotionScope,
    PromotionStatus,
    StackingPolicy,
    TargetRole,
    TargetType,
)

ORG_ID = UUID(int=1)
LOCATION_ID = UUID(int=2)
USER_ID = UUID(int=3)
COFFEE_PRODUCT_ID = UUID(int=10)
PASTRY_PRODUCT_ID = UUID(int=11)


def _item(
    *, item_id: int, product_id: UUID, price: int, modifier: int = 0, quantity: int = 1
) -> PricingItem:
    return PricingItem(
        id=UUID(int=item_id),
        category_id=None,
        product_id=product_id,
        variant_id=UUID(int=item_id + 100),
        quantity=quantity,
        base_price_minor=price,
        modifier_price_minor=modifier,
    )


def _target(
    promotion_id: UUID,
    *,
    role: TargetRole,
    product_id: UUID,
    quantity: int = 1,
    sort_order: int = 0,
) -> PromotionTarget:
    return PromotionTarget(
        id=uuid4(),
        promotion_id=promotion_id,
        role=role,
        target_type=TargetType.PRODUCT,
        target_id=product_id,
        quantity=quantity,
        sort_order=sort_order,
    )


def _promotion(
    *,
    promotion_id: int,
    kind: DiscountKind,
    scope: PromotionScope,
    percent: str | None = None,
    amount: int | None = None,
    fixed_price: int | None = None,
    priority: int = 0,
    stacking: StackingPolicy = StackingPolicy.STACKABLE,
    include_modifiers: bool = False,
    minimum_subtotal: int | None = None,
    maximum_discount: int | None = None,
    targets: tuple[PromotionTarget, ...] = (),
    schedules: tuple[PromotionSchedule, ...] = (),
) -> Promotion:
    identifier = UUID(int=promotion_id)
    return Promotion(
        id=identifier,
        organization_id=ORG_ID,
        name=f"Promotion {promotion_id}",
        pos_name=f"Promo {promotion_id}",
        status=PromotionStatus.ACTIVE,
        application_mode=ApplicationMode.AUTOMATIC,
        discount_kind=kind,
        scope=scope,
        percent_rate=Decimal(percent) if percent is not None else None,
        amount_minor=amount,
        fixed_price_minor=fixed_price,
        priority=priority,
        stacking_policy=stacking,
        include_modifier_price=include_modifiers,
        minimum_subtotal_minor=minimum_subtotal,
        maximum_discount_minor=maximum_discount,
        valid_from=None,
        valid_to=None,
        all_locations=True,
        requires_override_permission=False,
        created_by=USER_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        targets=targets,
        schedules=schedules,
    )


def _price(
    items: tuple[PricingItem, ...], promotions: tuple[Promotion, ...], at: datetime | None = None
):
    return price_order(
        items,
        promotions,
        location_id=LOCATION_ID,
        location_timezone="Asia/Almaty",
        occurred_at=at or datetime(2026, 1, 5, 10, tzinfo=UTC),
    )


@pytest.mark.parametrize(("modifier", "expected_total"), [(0, 2500), (300, 2800)])
def test_combo_fixed_price_preserves_modifier_upcharge(
    modifier: int, expected_total: int
) -> None:
    promotion_id = UUID(int=1000)
    promotion = _promotion(
        promotion_id=promotion_id.int,
        kind=DiscountKind.FIXED_PRICE,
        scope=PromotionScope.COMBO,
        fixed_price=2500,
        targets=(
            _target(
                promotion_id,
                role=TargetRole.COMBO_COMPONENT,
                product_id=COFFEE_PRODUCT_ID,
            ),
            _target(
                promotion_id,
                role=TargetRole.COMBO_COMPONENT,
                product_id=PASTRY_PRODUCT_ID,
                sort_order=1,
            ),
        ),
    )
    result = _price(
        (
            _item(
                item_id=20,
                product_id=COFFEE_PRODUCT_ID,
                price=1800,
                modifier=modifier,
            ),
            _item(item_id=21, product_id=PASTRY_PRODUCT_ID, price=1500),
        ),
        (promotion,),
    )

    assert result.subtotal_minor == 3300 + modifier
    assert result.discount_total_minor == 800
    assert result.total_minor == expected_total
    assert sum(result.item_discount_minor.values()) == 800


@pytest.mark.parametrize(
    ("local_hour", "local_minute", "matches"),
    [(14, 59, False), (15, 0, True), (16, 59, True), (17, 0, False)],
)
def test_schedule_uses_location_timezone_and_half_open_interval(
    local_hour: int, local_minute: int, matches: bool
) -> None:
    promotion_id = UUID(int=1001)
    schedule = PromotionSchedule(
        id=uuid4(),
        promotion_id=promotion_id,
        weekday=0,
        start_local_time=time(15),
        end_local_time=time(17),
    )
    promotion = _promotion(
        promotion_id=promotion_id.int,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ITEM,
        percent="20",
        targets=(
            _target(
                promotion_id,
                role=TargetRole.ELIGIBLE,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
        schedules=(schedule,),
    )
    # Asia/Almaty is UTC+05:00; the chosen date is a Monday in both zones.
    occurred_at = datetime(2026, 1, 5, local_hour - 5, local_minute, tzinfo=UTC)
    result = _price(
        (_item(item_id=30, product_id=COFFEE_PRODUCT_ID, price=1800),),
        (promotion,),
        occurred_at,
    )

    assert result.discount_total_minor == (360 if matches else 0)


def test_bogo_buy_two_get_one_discounts_exactly_one_of_three_units() -> None:
    promotion_id = UUID(int=1002)
    promotion = _promotion(
        promotion_id=promotion_id.int,
        kind=DiscountKind.BOGO,
        scope=PromotionScope.ITEM,
        targets=(
            _target(
                promotion_id,
                role=TargetRole.BUY,
                product_id=COFFEE_PRODUCT_ID,
                quantity=2,
            ),
            _target(
                promotion_id,
                role=TargetRole.GET,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
    )
    result = _price(
        (
            _item(
                item_id=40,
                product_id=COFFEE_PRODUCT_ID,
                price=1700,
                quantity=3,
            ),
        ),
        (promotion,),
    )

    assert result.subtotal_minor == 5100
    assert result.discount_total_minor == 1700
    assert result.total_minor == 3400


def test_bogo_repeats_complete_buy_two_get_one_groups_without_reusing_units() -> None:
    promotion_id = UUID(int=1008)
    promotion = _promotion(
        promotion_id=promotion_id.int,
        kind=DiscountKind.BOGO,
        scope=PromotionScope.ITEM,
        targets=(
            _target(
                promotion_id,
                role=TargetRole.BUY,
                product_id=COFFEE_PRODUCT_ID,
                quantity=2,
            ),
            _target(
                promotion_id,
                role=TargetRole.GET,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
    )
    result = _price(
        (
            _item(
                item_id=41,
                product_id=COFFEE_PRODUCT_ID,
                price=1700,
                quantity=6,
            ),
        ),
        (promotion,),
    )

    assert result.discount_total_minor == 3400
    assert result.total_minor == 6800


def test_item_minimum_subtotal_does_not_count_noneligible_items() -> None:
    promotion_id = UUID(int=1009)
    promotion = _promotion(
        promotion_id=promotion_id.int,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ITEM,
        percent="20",
        minimum_subtotal=1000,
        targets=(
            _target(
                promotion_id,
                role=TargetRole.ELIGIBLE,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
    )
    result = _price(
        (
            _item(item_id=42, product_id=COFFEE_PRODUCT_ID, price=500),
            _item(item_id=43, product_id=PASTRY_PRODUCT_ID, price=1000),
        ),
        (promotion,),
    )

    assert result.discount_total_minor == 0
    assert result.total_minor == 1500


def test_stackable_item_then_order_percent_is_sequential() -> None:
    item_promotion_id = UUID(int=1003)
    item_promotion = _promotion(
        promotion_id=item_promotion_id.int,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ITEM,
        percent="20",
        priority=100,
        targets=(
            _target(
                item_promotion_id,
                role=TargetRole.ELIGIBLE,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
    )
    order_promotion = _promotion(
        promotion_id=1004,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ORDER,
        percent="10",
        priority=50,
    )
    result = _price(
        (_item(item_id=50, product_id=COFFEE_PRODUCT_ID, price=1000),),
        (order_promotion, item_promotion),
    )

    assert [value.discount_total_minor for value in result.discounts] == [200, 80]
    assert result.discount_total_minor == 280
    assert result.total_minor == 720


def test_highest_priority_exclusive_promotion_is_the_only_match() -> None:
    high = _promotion(
        promotion_id=1005,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ORDER,
        percent="20",
        priority=100,
        stacking=StackingPolicy.EXCLUSIVE,
    )
    low = _promotion(
        promotion_id=1006,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ORDER,
        percent="50",
        priority=50,
        stacking=StackingPolicy.EXCLUSIVE,
    )
    result = _price(
        (_item(item_id=60, product_id=COFFEE_PRODUCT_ID, price=1000),),
        (low, high),
    )

    assert [value.promotion_id for value in result.discounts] == [high.id]
    assert result.total_minor == 800


def test_item_unit_is_claimed_only_by_the_highest_priority_item_promotion() -> None:
    promotion_id = UUID(int=1010)
    high = _promotion(
        promotion_id=promotion_id.int,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ITEM,
        percent="20",
        priority=100,
        targets=(
            _target(
                promotion_id,
                role=TargetRole.ELIGIBLE,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
    )
    lower_id = UUID(int=1011)
    low = _promotion(
        promotion_id=lower_id.int,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ITEM,
        percent="50",
        priority=50,
        targets=(
            _target(
                lower_id,
                role=TargetRole.ELIGIBLE,
                product_id=COFFEE_PRODUCT_ID,
            ),
        ),
    )

    result = _price(
        (_item(item_id=61, product_id=COFFEE_PRODUCT_ID, price=1000),),
        (low, high),
    )

    assert [discount.promotion_id for discount in result.discounts] == [high.id]
    assert result.total_minor == 800


def test_maximum_discount_caps_percentage_promotion() -> None:
    promotion = _promotion(
        promotion_id=1012,
        kind=DiscountKind.PERCENT,
        scope=PromotionScope.ORDER,
        percent="50",
        maximum_discount=100,
    )

    result = _price(
        (_item(item_id=62, product_id=COFFEE_PRODUCT_ID, price=1000),),
        (promotion,),
    )

    assert result.discount_total_minor == 100
    assert result.total_minor == 900


def test_largest_remainder_is_exact_and_ties_use_stable_item_order() -> None:
    first, second, third = UUID(int=1), UUID(int=2), UUID(int=3)

    allocation = largest_remainder_allocate(2, ((third, 1), (second, 1), (first, 1)))

    assert allocation == {third: 0, second: 1, first: 1}
    assert sum(allocation.values()) == 2


@pytest.mark.parametrize(
    ("kind", "percent", "amount"),
    [
        (DiscountKind.PERCENT, "100", None),
        (DiscountKind.FIXED_AMOUNT, None, 1000),
    ],
)
def test_discount_can_reach_zero_but_never_make_total_negative(
    kind: DiscountKind, percent: str | None, amount: int | None
) -> None:
    promotion = _promotion(
        promotion_id=1007,
        kind=kind,
        scope=PromotionScope.ORDER,
        percent=percent,
        amount=amount,
    )
    result = _price(
        (_item(item_id=70, product_id=COFFEE_PRODUCT_ID, price=500),),
        (promotion,),
    )

    assert result.discount_total_minor == 500
    assert result.total_minor == 0
