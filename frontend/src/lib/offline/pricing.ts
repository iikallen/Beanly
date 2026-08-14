import type { OfflinePromotion, SalesOrderDiscount } from "@/lib/api";

import type { OfflineOrder, OfflineOrderItem } from "./types";

type Unit = { item: OfflineOrderItem; key: string; gross: bigint; base: bigint; remaining: bigint; claimed: boolean };

export function priceOfflineOrder(
  order: OfflineOrder,
  promotions: OfflinePromotion[],
  manualIds: string[],
  timezone: string,
  occurredAt = new Date(order.updated_at),
) {
  const units = [...order.items].sort((left, right) => left.id.localeCompare(right.id)).flatMap((item) => Array.from({ length: item.quantity }, (_, index) => ({
    item, key: `${item.id}:${index}`, gross: BigInt(item.unit_price_minor), base: BigInt(item.base_price_minor), remaining: BigInt(item.unit_price_minor), claimed: false,
  })));
  const selected = new Set(manualIds);
  let candidates = promotions.filter((promotion) =>
    (promotion.application_mode === "AUTOMATIC" || selected.has(promotion.promotion_id)) && available(promotion, occurredAt, timezone),
  ).sort((left, right) => right.priority - left.priority);
  candidates = candidates.find((promotion) => promotion.stacking === "EXCLUSIVE") ? [candidates.find((promotion) => promotion.stacking === "EXCLUSIVE")!] : candidates;
  const applied: SalesOrderDiscount[] = [];

  for (const phase of [
    (promotion: OfflinePromotion) => promotion.scope !== "ORDER",
    (promotion: OfflinePromotion) => promotion.scope === "ORDER" && promotion.kind === "FIXED_AMOUNT",
    (promotion: OfflinePromotion) => promotion.scope === "ORDER" && promotion.kind === "PERCENT",
  ]) {
    for (const promotion of candidates) {
      if (!phase(promotion)) continue;
      const chosen = choose(units, promotion);
      if (!chosen.length) continue;
      const eligible = chosen.reduce((sum, unit) => sum + eligibleAmount(unit, promotion), BigInt(0));
      if (promotion.minimum_subtotal_minor && eligible < BigInt(promotion.minimum_subtotal_minor)) continue;
      let discount = configuredDiscount(promotion, eligible);
      if (promotion.maximum_discount_minor) discount = min(discount, BigInt(promotion.maximum_discount_minor));
      discount = min(discount, chosen.reduce((sum, unit) => sum + unit.remaining, BigInt(0)));
      if (discount <= BigInt(0)) continue;
      const itemWeights = new Map<string, bigint>();
      for (const unit of chosen) itemWeights.set(unit.item.id, (itemWeights.get(unit.item.id) ?? BigInt(0)) + eligibleAmount(unit, promotion));
      const itemAllocations = allocate(discount, [...itemWeights]);
      for (const [itemId, allocated] of itemAllocations) {
        let remaining = allocated;
        for (const unit of chosen.filter((value) => value.item.id === itemId).sort((left, right) => left.key.localeCompare(right.key))) {
          const consumed = min(unit.remaining, remaining);
          unit.remaining -= consumed; remaining -= consumed;
        }
      }
      if (promotion.scope !== "ORDER") for (const unit of chosen) unit.claimed = true;
      applied.push({
        id: promotion.promotion_id, promotion_id: promotion.promotion_id, client_discount_id: promotion.application_mode === "MANUAL" ? promotion.promotion_id : null,
        source: promotion.application_mode === "AUTOMATIC" ? "AUTOMATIC" : "MANUAL", promotion_name: promotion.name,
        discount_kind: promotion.kind, scope: promotion.scope, percent_rate: promotion.percent_rate,
        configured_amount_minor: promotion.amount_minor ?? promotion.fixed_price_minor, promo_code_snapshot: null, reason: null,
        applied_by_user_id: null, applied_at: occurredAt.toISOString(), discount_total_minor: String(discount), sort_order: applied.length, audience_kind: null,
        allocations: [...itemAllocations].filter(([, value]) => value > BigInt(0)).map(([order_item_id, value], index) => ({ order_item_id, eligible_amount_minor: String(itemWeights.get(order_item_id) ?? BigInt(0)), discount_amount_minor: String(value), sort_order: index })),
      });
    }
  }

  const itemDiscounts = new Map<string, bigint>();
  for (const discount of applied) for (const allocation of discount.allocations) itemDiscounts.set(allocation.order_item_id, (itemDiscounts.get(allocation.order_item_id) ?? BigInt(0)) + BigInt(allocation.discount_amount_minor));
  for (const item of order.items) {
    item.discount_amount_minor = String(itemDiscounts.get(item.id) ?? BigInt(0));
    item.net_line_total_minor = String(BigInt(item.line_total_minor) - BigInt(item.discount_amount_minor));
  }
  const subtotal = order.items.reduce((sum, item) => sum + BigInt(item.line_total_minor), BigInt(0));
  const discountTotal = applied.reduce((sum, discount) => sum + BigInt(discount.discount_total_minor), BigInt(0));
  return { subtotal_minor: String(subtotal), discount_total_minor: String(discountTotal), total_minor: String(subtotal - discountTotal), discounts: applied };
}

function choose(units: Unit[], promotion: OfflinePromotion) {
  if (promotion.scope === "ORDER") return units.filter((unit) => unit.remaining > BigInt(0));
  if (promotion.kind === "BOGO") {
    const buy = promotion.targets.find((target) => target.role === "BUY");
    const get = promotion.targets.find((target) => target.role === "GET") ?? buy;
    if (!buy || !get) return [];
    const buys = units.filter((unit) => !unit.claimed && matches(unit.item, buy));
    const gets = units.filter((unit) => !unit.claimed && matches(unit.item, get));
    const sameTarget = buy.target_type === get.target_type && buy.target_id === get.target_id;
    const groups = sameTarget ? Math.floor(buys.length / (buy.quantity + get.quantity)) : Math.min(Math.floor(buys.length / buy.quantity), Math.floor(gets.length / get.quantity));
    return (sameTarget ? buys : gets).sort((left, right) => left.remaining === right.remaining ? left.key.localeCompare(right.key) : left.remaining < right.remaining ? -1 : 1).slice(0, groups * get.quantity);
  }
  if (promotion.scope === "COMBO") {
    const chosen: Unit[] = [];
    for (const target of promotion.targets.filter((value) => value.role === "COMBO_COMPONENT").sort((a, b) => a.sort_order - b.sort_order)) {
      const matchesTarget = units.filter((unit) => !unit.claimed && !chosen.includes(unit) && matches(unit.item, target)).slice(0, target.quantity);
      if (matchesTarget.length < target.quantity) return [];
      chosen.push(...matchesTarget);
    }
    return chosen;
  }
  const eligibleTargets = promotion.targets.filter((target) => target.role === "ELIGIBLE");
  return units.filter((unit) => !unit.claimed && (!eligibleTargets.length || eligibleTargets.some((target) => matches(unit.item, target))));
}

function matches(item: OfflineOrderItem, target: OfflinePromotion["targets"][number]) {
  return target.target_type === "ALL" || (target.target_type === "CATEGORY" ? item.category_id : target.target_type === "PRODUCT" ? item.product_id : item.product_variant_id) === target.target_id;
}

function eligibleAmount(unit: Unit, promotion: OfflinePromotion) { return promotion.include_modifier_price ? unit.remaining : min(unit.remaining, unit.base); }

function configuredDiscount(promotion: OfflinePromotion, eligible: bigint) {
  if (promotion.kind === "PERCENT" && promotion.percent_rate) return divideRounded(eligible * percentScale(promotion.percent_rate), BigInt(1_000_000));
  if (promotion.kind === "FIXED_AMOUNT" && promotion.amount_minor) return min(eligible, BigInt(promotion.amount_minor));
  if (promotion.kind === "FIXED_PRICE" && promotion.fixed_price_minor) return eligible > BigInt(promotion.fixed_price_minor) ? eligible - BigInt(promotion.fixed_price_minor) : BigInt(0);
  if (promotion.kind === "BOGO") return eligible;
  return BigInt(0);
}

function allocate(total: bigint, values: ReadonlyArray<readonly [string, bigint]>) {
  const denominator = values.reduce((sum, [, value]) => sum + value, BigInt(0));
  const output = new Map(values.map(([key]) => [key, BigInt(0)]));
  if (!denominator) return output;
  const ranked = values.map(([key, value], index) => ({ key, index, share: total * value / denominator, remainder: total * value % denominator }));
  let remaining = total - ranked.reduce((sum, row) => sum + row.share, BigInt(0));
  ranked.sort((a, b) => a.remainder === b.remainder ? a.index - b.index : a.remainder > b.remainder ? -1 : 1);
  for (const row of ranked) { if (remaining > BigInt(0)) { row.share += BigInt(1); remaining -= BigInt(1); } output.set(row.key, row.share); }
  return output;
}

function available(promotion: OfflinePromotion, now: Date, timezone: string) {
  if (promotion.valid_from && now < new Date(promotion.valid_from)) return false;
  if (promotion.valid_to && now >= new Date(promotion.valid_to)) return false;
  if (!promotion.schedules.length) return true;
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: timezone, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(now).map((part) => [part.type, part.value]));
  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday);
  const local = `${parts.hour}:${parts.minute}`;
  return promotion.schedules.some((schedule) => schedule.weekday === weekday && schedule.start_local_time.slice(0, 5) <= local && local < schedule.end_local_time.slice(0, 5));
}

function percentScale(value: string) { const [whole, fraction = ""] = value.split("."); return BigInt(whole) * BigInt(10_000) + BigInt((fraction + "0000").slice(0, 4)); }
function divideRounded(value: bigint, denominator: bigint) { return (value + denominator / BigInt(2)) / denominator; }
function min(left: bigint, right: bigint) { return left < right ? left : right; }
