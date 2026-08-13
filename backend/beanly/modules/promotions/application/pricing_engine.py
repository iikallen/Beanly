from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from beanly.modules.promotions.domain.entities import (
    AppliedDiscount,
    DiscountAllocation,
    PricingItem,
    PricingResult,
    Promotion,
    PromotionTarget,
)
from beanly.modules.promotions.domain.enums import (
    ApplicationMode,
    DiscountKind,
    DiscountSource,
    PromotionScope,
    PromotionStatus,
    StackingPolicy,
    TargetRole,
    TargetType,
)


@dataclass(frozen=True, slots=True)
class SelectedPromotion:
    promotion: Promotion
    source: DiscountSource
    client_discount_id: UUID | None = None
    code: str | None = None
    applied_by_user_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CustomDiscount:
    client_discount_id: UUID
    kind: DiscountKind
    percent_rate: Decimal | None
    amount_minor: int | None
    reason: str
    applied_by_user_id: UUID


@dataclass(slots=True)
class _Unit:
    item: PricingItem
    ordinal: int
    remaining: int
    item_phase_claimed: bool = False


def price_order(
    items: tuple[PricingItem, ...],
    promotions: tuple[Promotion, ...],
    *,
    location_id: UUID,
    location_timezone: str,
    occurred_at: datetime,
    selected: tuple[SelectedPromotion, ...] = (),
    custom: tuple[CustomDiscount, ...] = (),
) -> PricingResult:
    """Pure deterministic pricing. All inputs are immutable snapshots."""
    if occurred_at.tzinfo is None:
        raise ValueError("Pricing time must be timezone-aware")
    now = occurred_at.astimezone(UTC)
    units = [
        _Unit(item, ordinal, item.unit_gross_minor)
        for item in sorted(items, key=lambda value: value.id.int)
        for ordinal in range(item.quantity)
    ]
    subtotal = sum(unit.remaining for unit in units)
    selected_by_id = {value.promotion.id: value for value in selected}
    candidates: list[tuple[Promotion, DiscountSource, SelectedPromotion | None]] = []
    for promotion in promotions:
        selected_value = selected_by_id.get(promotion.id)
        if promotion.application_mode == ApplicationMode.AUTOMATIC:
            source = DiscountSource.AUTOMATIC
        elif selected_value is not None:
            source = selected_value.source
        else:
            continue
        if _available(promotion, location_id, location_timezone, now):
            candidates.append((promotion, source, selected_value))
    candidates.sort(key=lambda value: (-value[0].priority, value[0].created_at, value[0].id.int))
    exclusive = next(
        (value for value in candidates if value[0].stacking_policy == StackingPolicy.EXCLUSIVE),
        None,
    )
    if exclusive is not None:
        candidates = [exclusive]

    applied: list[AppliedDiscount] = []
    phases = (
        lambda p: p.scope in {PromotionScope.ITEM, PromotionScope.COMBO},
        lambda p: p.scope == PromotionScope.ORDER and p.discount_kind == DiscountKind.FIXED_AMOUNT,
        lambda p: p.scope == PromotionScope.ORDER and p.discount_kind == DiscountKind.PERCENT,
    )
    for phase in phases:
        for promotion, source, selection in candidates:
            if not phase(promotion):
                continue
            result = _apply_promotion(units, promotion, source, selection, len(applied), now)
            if result is not None:
                applied.append(result)

    for value in custom:
        result = _apply_custom(units, value, len(applied), now)
        if result is not None:
            applied.append(result)

    item_discount: dict[UUID, int] = {item.id: 0 for item in items}
    for discount in applied:
        for allocation in discount.allocations:
            item_discount[allocation.order_item_id] += allocation.discount_amount_minor
    total = sum(unit.remaining for unit in units)
    return PricingResult(
        subtotal,
        subtotal - total,
        total,
        item_discount,
        tuple(applied),
        now,
    )


def largest_remainder_allocate(
    amount_minor: int, weights: tuple[tuple[UUID, int], ...]
) -> dict[UUID, int]:
    """Allocate an integer amount exactly, ties broken by stable UUID order."""
    positive = tuple((key, value) for key, value in weights if value > 0)
    total = sum(value for _, value in positive)
    amount = min(max(amount_minor, 0), total)
    if total == 0 or amount == 0:
        return {key: 0 for key, _ in weights}
    raw = [(key, Decimal(amount) * Decimal(weight) / Decimal(total)) for key, weight in positive]
    allocated = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in raw}
    remainder = amount - sum(allocated.values())
    order = sorted(raw, key=lambda pair: (-(pair[1] % 1), pair[0].int))
    for key, _ in order[:remainder]:
        allocated[key] += 1
    return {key: allocated.get(key, 0) for key, _ in weights}


def _available(
    promotion: Promotion,
    location_id: UUID,
    timezone: str,
    now: datetime,
) -> bool:
    if promotion.status != PromotionStatus.ACTIVE:
        return False
    if promotion.valid_from is not None and now < promotion.valid_from.astimezone(UTC):
        return False
    if promotion.valid_to is not None and now >= promotion.valid_to.astimezone(UTC):
        return False
    if not promotion.all_locations and location_id not in promotion.location_ids:
        return False
    if not promotion.schedules:
        return True
    local = now.astimezone(ZoneInfo(timezone))
    return any(
        schedule.weekday == local.weekday()
        and schedule.start_local_time <= local.time().replace(tzinfo=None) < schedule.end_local_time
        for schedule in promotion.schedules
    )


def _apply_promotion(
    units: list[_Unit],
    promotion: Promotion,
    source: DiscountSource,
    selection: SelectedPromotion | None,
    sort_order: int,
    now: datetime,
) -> AppliedDiscount | None:
    if promotion.scope == PromotionScope.ORDER:
        chosen = [unit for unit in units if unit.remaining > 0]
        discount = _configured_discount(promotion, sum(unit.remaining for unit in chosen))
    elif promotion.discount_kind == DiscountKind.BOGO:
        chosen, discount = _bogo(units, promotion)
    elif promotion.scope == PromotionScope.COMBO:
        chosen, discount = _combo(units, promotion)
    else:
        chosen = [
            unit
            for unit in units
            if not unit.item_phase_claimed and _matches_any(unit.item, promotion.targets)
        ]
        eligible = sum(_eligible_unit(unit, promotion) for unit in chosen)
        discount = _configured_discount(promotion, eligible)
    eligible_total = sum(_eligible_unit(unit, promotion) for unit in chosen)
    if (
        promotion.minimum_subtotal_minor is not None
        and eligible_total < promotion.minimum_subtotal_minor
    ):
        return None
    if not chosen or discount <= 0:
        return None
    if promotion.maximum_discount_minor is not None:
        discount = min(discount, promotion.maximum_discount_minor)
    weights = _group_weights(chosen, promotion)
    allocation = largest_remainder_allocate(discount, weights)
    _consume(units, allocation)
    if promotion.scope in {PromotionScope.ITEM, PromotionScope.COMBO}:
        for unit in chosen:
            unit.item_phase_claimed = True
    return AppliedDiscount(
        uuid4(),
        promotion.id,
        source,
        promotion.name,
        promotion.discount_kind,
        promotion.scope,
        promotion.percent_rate,
        promotion.amount_minor or promotion.fixed_price_minor,
        selection.code if selection else None,
        None,
        sum(allocation.values()),
        _config_hash(promotion),
        sort_order,
        selection.client_discount_id if selection else None,
        selection.applied_by_user_id if selection else None,
        now,
        _allocations(weights, allocation),
    )


def _apply_custom(
    units: list[_Unit], value: CustomDiscount, sort_order: int, now: datetime
) -> AppliedDiscount | None:
    weights = _group_remaining(units)
    eligible = sum(amount for _, amount in weights)
    if value.kind == DiscountKind.PERCENT and value.percent_rate is not None:
        amount = _round_minor(Decimal(eligible) * value.percent_rate / Decimal(100))
    elif value.kind == DiscountKind.FIXED_AMOUNT and value.amount_minor is not None:
        amount = min(value.amount_minor, eligible)
    else:
        raise ValueError("Custom discount must be PERCENT or FIXED_AMOUNT")
    allocation = largest_remainder_allocate(amount, weights)
    _consume(units, allocation)
    return AppliedDiscount(
        uuid4(),
        None,
        DiscountSource.CUSTOM,
        "Custom discount",
        value.kind,
        PromotionScope.ORDER,
        value.percent_rate,
        value.amount_minor,
        None,
        value.reason,
        sum(allocation.values()),
        hashlib.sha256(
            f"{value.kind}:{value.percent_rate}:{value.amount_minor}:{value.reason}".encode()
        ).hexdigest(),
        sort_order,
        value.client_discount_id,
        value.applied_by_user_id,
        now,
        _allocations(weights, allocation),
    )


def _configured_discount(promotion: Promotion, eligible: int) -> int:
    if promotion.discount_kind == DiscountKind.PERCENT and promotion.percent_rate is not None:
        return min(eligible, _round_minor(Decimal(eligible) * promotion.percent_rate / 100))
    if promotion.discount_kind == DiscountKind.FIXED_AMOUNT and promotion.amount_minor is not None:
        return min(eligible, promotion.amount_minor)
    if (
        promotion.discount_kind == DiscountKind.FIXED_PRICE
        and promotion.fixed_price_minor is not None
    ):
        return max(0, eligible - promotion.fixed_price_minor)
    return 0


def _bogo(units: list[_Unit], promotion: Promotion) -> tuple[list[_Unit], int]:
    buy = next((value for value in promotion.targets if value.role == TargetRole.BUY), None)
    get = next((value for value in promotion.targets if value.role == TargetRole.GET), buy)
    if buy is None or get is None:
        return [], 0
    buy_units = [unit for unit in units if not unit.item_phase_claimed and _matches(unit.item, buy)]
    get_units = [unit for unit in units if not unit.item_phase_claimed and _matches(unit.item, get)]
    groups = min(len(buy_units) // buy.quantity, len(get_units) // get.quantity)
    if buy.target_type == get.target_type and buy.target_id == get.target_id:
        groups = len(buy_units) // (buy.quantity + get.quantity)
        chosen = sorted(
            buy_units, key=lambda unit: (unit.remaining, unit.item.id.int, unit.ordinal)
        )[: groups * get.quantity]
    else:
        chosen = sorted(
            get_units, key=lambda unit: (unit.remaining, unit.item.id.int, unit.ordinal)
        )[: groups * get.quantity]
    return chosen, sum(_eligible_unit(unit, promotion) for unit in chosen)


def _combo(units: list[_Unit], promotion: Promotion) -> tuple[list[_Unit], int]:
    targets = sorted(
        (value for value in promotion.targets if value.role == TargetRole.COMBO_COMPONENT),
        key=lambda value: (value.sort_order, value.id.int),
    )
    chosen: list[_Unit] = []
    used: set[tuple[UUID, int]] = set()
    for target in targets:
        matches = [
            unit
            for unit in units
            if not unit.item_phase_claimed
            and (unit.item.id, unit.ordinal) not in used
            and _matches(unit.item, target)
        ]
        matches.sort(key=lambda unit: (unit.item.id.int, unit.ordinal))
        if len(matches) < target.quantity:
            return [], 0
        selected = matches[: target.quantity]
        chosen.extend(selected)
        used.update((unit.item.id, unit.ordinal) for unit in selected)
    eligible = sum(_eligible_unit(unit, promotion) for unit in chosen)
    return chosen, _configured_discount(promotion, eligible)


def _eligible_unit(unit: _Unit, promotion: Promotion) -> int:
    if promotion.include_modifier_price:
        return unit.remaining
    return min(unit.remaining, unit.item.base_price_minor)


def _group_weights(units: list[_Unit], promotion: Promotion) -> tuple[tuple[UUID, int], ...]:
    grouped: dict[UUID, int] = {}
    for unit in units:
        grouped[unit.item.id] = grouped.get(unit.item.id, 0) + _eligible_unit(unit, promotion)
    return tuple(sorted(grouped.items(), key=lambda value: value[0].int))


def _group_remaining(units: list[_Unit]) -> tuple[tuple[UUID, int], ...]:
    grouped: dict[UUID, int] = {}
    for unit in units:
        grouped[unit.item.id] = grouped.get(unit.item.id, 0) + unit.remaining
    return tuple(sorted(grouped.items(), key=lambda value: value[0].int))


def _consume(units: list[_Unit], allocation: dict[UUID, int]) -> None:
    for item_id, amount in allocation.items():
        candidates = sorted(
            (unit for unit in units if unit.item.id == item_id),
            key=lambda unit: unit.ordinal,
        )
        left = amount
        for unit in candidates:
            take = min(left, unit.remaining)
            unit.remaining -= take
            left -= take
            if left == 0:
                break
        if left:
            raise ValueError("Discount allocation exceeds item remainder")


def _allocations(
    weights: tuple[tuple[UUID, int], ...], allocation: dict[UUID, int]
) -> tuple[DiscountAllocation, ...]:
    return tuple(
        DiscountAllocation(item_id, eligible, allocation[item_id], index)
        for index, (item_id, eligible) in enumerate(weights)
        if allocation[item_id] > 0
    )


def _matches_any(item: PricingItem, targets: tuple[PromotionTarget, ...]) -> bool:
    eligible = tuple(value for value in targets if value.role == TargetRole.ELIGIBLE)
    return not eligible or any(_matches(item, value) for value in eligible)


def _matches(item: PricingItem, target: PromotionTarget) -> bool:
    if target.target_type == TargetType.ALL:
        return True
    if target.target_type == TargetType.CATEGORY:
        return item.category_id == target.target_id
    if target.target_type == TargetType.PRODUCT:
        return item.product_id == target.target_id
    return item.variant_id == target.target_id


def _round_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _config_hash(value: Promotion) -> str:
    payload = {
        "id": str(value.id),
        "kind": value.discount_kind,
        "scope": value.scope,
        "percent": str(value.percent_rate) if value.percent_rate is not None else None,
        "amount": value.amount_minor,
        "fixed": value.fixed_price_minor,
        "modifier": value.include_modifier_price,
        "min": value.minimum_subtotal_minor,
        "max": value.maximum_discount_minor,
        "targets": [
            [target.role, target.target_type, str(target.target_id), target.quantity]
            for target in value.targets
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
