"use client";

import { Clock3, Minus, Plus, ShoppingBag, UtensilsCrossed } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, type OnlineFulfillmentOptions, type OnlineFulfillmentSelection, type OnlineFulfillmentTiming, type OnlineFulfillmentType, type OnlineQuote, type OnlineQuoteItem, type OnlineOrderingLocation, type PublicModifierGroup, type PublicOrderingMenu } from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

type PublicVariant = PublicOrderingMenu["categories"][number]["products"][number]["variants"][number];
type CartLine = OnlineQuoteItem & { product_name: string; variant_name: string; modifier_names: string[] };

export function PublicOrderClient({ slug }: { slug: string }) {
  const router = useRouter();
  const [location, setLocation] = useState<OnlineOrderingLocation | null>(null);
  const [menu, setMenu] = useState<PublicOrderingMenu | null>(null);
  const [station, setStation] = useState("");
  const [cart, setCart] = useState<CartLine[]>([]);
  const [quote, setQuote] = useState<OnlineQuote | null>(null);
  const [fulfillmentOptions, setFulfillmentOptions] = useState<OnlineFulfillmentOptions | null>(null);
  const [fulfillmentType, setFulfillmentType] = useState<OnlineFulfillmentType>("PICKUP");
  const [fulfillmentTiming, setFulfillmentTiming] = useState<OnlineFulfillmentTiming>("ASAP");
  const [requestedAt, setRequestedAt] = useState("");
  const [deliveryZoneId, setDeliveryZoneId] = useState("");
  const [deliveryAddress, setDeliveryAddress] = useState("");
  const [guestInstructions, setGuestInstructions] = useState("");
  const [promoCode, setPromoCode] = useState("");
  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const clientOrderId = useRef("");

  useEffect(() => {
    clientOrderId.current ||= crypto.randomUUID();
    const stationToken = new URLSearchParams(window.location.search).get("station") ?? "";
    let cancelled = false;
    Promise.all([api.getPublicOrdering(slug, stationToken || undefined), api.getPublicOrderingMenu(slug), api.getPublicFulfillmentOptions(slug, stationToken || undefined)])
      .then(([nextLocation, nextMenu, nextFulfillment]) => { if (!cancelled) { setStation(stationToken); setLocation(nextLocation); setMenu(nextMenu); setFulfillmentOptions(nextFulfillment); setFulfillmentType(stationToken ? "PICKUP" : nextFulfillment.default_fulfillment_type); } })
      .catch((caught) => { if (!cancelled) setError(messageOf(caught)); });
    return () => { cancelled = true; };
  }, [slug]);

  const count = useMemo(() => cart.reduce((sum, item) => sum + item.quantity, 0), [cart]);

  function add(productName: string, variant: PublicVariant, modifierOptionIds: string[], modifierNames: string[], note: string) {
    setQuote(null);
    setCart((current) => current.length >= 50 ? current : [...current, { client_item_id: crypto.randomUUID(), variant_id: variant.id, quantity: 1, modifier_option_ids: modifierOptionIds, note: note || undefined, product_name: productName, variant_name: variant.name, modifier_names: modifierNames }]);
  }

  function quantity(id: string, delta: number) {
    setQuote(null);
    setCart((current) => current.flatMap((item) => item.client_item_id === id ? (item.quantity + delta > 0 ? [{ ...item, quantity: Math.min(99, item.quantity + delta) }] : []) : [item]));
  }

  async function getQuote() {
    setBusy(true); setError("");
    try {
      const next = await api.quotePublicOrder(slug, { client_order_id: clientOrderId.current, station_token: station || undefined, promo_code: promoCode.trim() || undefined, items: cart.map(toQuoteItem), ...selection() });
      setQuote(next);
    } catch (caught) {
      if (isSlotConflict(caught)) {
        setRequestedAt("");
        api.getPublicFulfillmentOptions(slug, station || undefined).then(setFulfillmentOptions).catch(() => undefined);
        setError("That time is no longer available. Choose another slot.");
      } else setError(messageOf(caught));
    }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!quote) return;
    setBusy(true); setError("");
    const input = { client_order_id: clientOrderId.current, station_token: station || undefined, promo_code: promoCode.trim() || undefined, items: cart.map(toQuoteItem), quote_revision: quote.quote_revision, guest_name: guestName.trim() || undefined, guest_phone: guestPhone.trim() || undefined, ...selection() };
    try {
      const order = await api.submitPublicOrder(slug, input);
      if (!order.status_token) throw new Error("Status link was not returned");
      router.push(`/order/status/${encodeURIComponent(order.status_token)}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "ONLINE_ORDER_QUOTE_CHANGED") await getQuote();
      if (isSlotConflict(caught)) {
        setQuote(null); setRequestedAt("");
        api.getPublicFulfillmentOptions(slug, station || undefined).then(setFulfillmentOptions).catch(() => undefined);
        setError("That time just filled up. Choose another slot and review your total again.");
      } else setError(messageOf(caught));
    } finally { setBusy(false); }
  }

  function selection(): OnlineFulfillmentSelection {
    const delivery = fulfillmentType === "DELIVERY";
    return {
      fulfillment_type: station ? "PICKUP" : fulfillmentType,
      fulfillment_timing: station ? "ASAP" : fulfillmentTiming,
      requested_at: !station && fulfillmentTiming === "SCHEDULED" ? requestedAt : null,
      delivery_zone_id: delivery ? deliveryZoneId : null,
      delivery_address: delivery ? deliveryAddress.trim() : null,
      guest_instructions: guestInstructions.trim() || null,
    };
  }

  function changeFulfillment(next: OnlineFulfillmentType) {
    setFulfillmentType(next); setQuote(null); setRequestedAt(""); setDeliveryZoneId(""); setDeliveryAddress("");
  }

  if (error && (!location || !menu || !fulfillmentOptions)) return <main className="public-order-state"><UtensilsCrossed /><h1>Menu unavailable</h1><p role="alert">{error}</p></main>;
  if (!location || !menu || !fulfillmentOptions) return <main className="public-order-state" aria-live="polite">Loading menu…</main>;
  const missingRequiredGuest = (location.guest_name_required && !guestName.trim()) || (!station && fulfillmentType === "PICKUP" && location.guest_phone_required_pickup && !guestPhone.trim());
  const missingFulfillment = !station && (fulfillmentTiming === "SCHEDULED" && !requestedAt || fulfillmentType === "DELIVERY" && (!deliveryZoneId || !deliveryAddress.trim()));
  const availabilityMessage = location.accepting_orders ? "Accepting orders" : location.unavailable_reason === "TEMPORARILY_PAUSED" ? "Temporarily not accepting orders" : location.unavailable_reason?.replaceAll("_", " ") || "Ordering paused";

  return <main className="public-order-page">
    <header className="public-order-hero"><div><p>{location.station ? `${location.station.kind.replaceAll("_", " ")} · ${location.station.label}` : titleCase(fulfillmentType)}</p><h1>{location.location_name}</h1><span aria-live="polite">{availabilityMessage}</span></div><ShoppingBag aria-hidden="true" /><strong aria-label={`${count} items in cart`}>{count}</strong></header>
    <section className="public-menu" aria-label="Menu">{menu.categories.map((category) => <div key={category.id}><h2>{category.name}</h2><div className="public-product-grid">{category.products.filter((product) => product.is_available).map((product) => <article key={product.id}><div><h3>{product.name}</h3>{product.description && <p>{product.description}</p>}</div>{product.variants.map((variant) => <VariantPicker currency={menu.currency_code} key={variant.id} onAdd={(optionIds, optionNames, note) => add(product.name, variant, optionIds, optionNames, note)} variant={variant} />)}</article>)}</div></div>)}</section>
    <aside className="public-cart" aria-label="Cart">
      <h2>Your order</h2>
      {cart.length === 0 ? <p>Add an item to continue.</p> : <>
        {cart.map((item) => <div className="public-cart-line" key={item.client_item_id}><span><strong>{item.product_name}</strong><small>{[item.variant_name, ...item.modifier_names].join(" · ")}</small></span><div><button type="button" aria-label={`Remove one ${item.product_name}`} onClick={() => quantity(item.client_item_id, -1)}><Minus /></button><b aria-label={`Quantity ${item.quantity}`}>{item.quantity}</b><button type="button" aria-label={`Add one ${item.product_name}`} disabled={item.quantity >= 99} onClick={() => quantity(item.client_item_id, 1)}><Plus /></button></div></div>)}
        {!station && <fieldset className="public-fulfillment"><legend>Fulfillment</legend><div>
          <button type="button" aria-pressed={fulfillmentType === "PICKUP"} disabled={!fulfillmentOptions.pickup_enabled} onClick={() => changeFulfillment("PICKUP")}>Pickup</button>
          <button type="button" aria-pressed={fulfillmentType === "DELIVERY"} disabled={!fulfillmentOptions.delivery_enabled} onClick={() => changeFulfillment("DELIVERY")}>Delivery</button>
        </div></fieldset>}
        {!station && <fieldset className="public-fulfillment"><legend>When</legend><div>
          <button type="button" aria-pressed={fulfillmentTiming === "ASAP"} onClick={() => { setFulfillmentTiming("ASAP"); setRequestedAt(""); setQuote(null); }}>ASAP</button>
          <button type="button" aria-pressed={fulfillmentTiming === "SCHEDULED"} disabled={fulfillmentOptions.slots.length === 0} onClick={() => { setFulfillmentTiming("SCHEDULED"); setQuote(null); }}>Scheduled</button>
        </div>{fulfillmentTiming === "ASAP" ? <small>Estimated for {minuteTime(fulfillmentOptions.asap_promised_at, fulfillmentOptions.timezone)}</small> : <label>Available time<select value={requestedAt} onChange={(event) => { setRequestedAt(event.target.value); setQuote(null); }}><option value="">Choose a time</option>{fulfillmentOptions.slots.map((slot) => <option disabled={slot.remaining_capacity < 1} key={slot.starts_at} value={slot.starts_at}>{minuteDateTime(slot.starts_at, fulfillmentOptions.timezone)}{slot.remaining_capacity < 1 ? " · Unavailable" : ""}</option>)}</select></label>}</fieldset>}
        {!station && fulfillmentType === "DELIVERY" && <div className="public-delivery">
          <label>Delivery zone<select value={deliveryZoneId} onChange={(event) => { setDeliveryZoneId(event.target.value); setQuote(null); }}><option value="">Choose a zone</option>{fulfillmentOptions.delivery_zones.filter((zone) => zone.enabled).map((zone) => <option key={zone.id} value={zone.id}>{zone.name}</option>)}</select></label>
          <label>Delivery address<textarea autoComplete="street-address" maxLength={1000} required value={deliveryAddress} onChange={(event) => { setDeliveryAddress(event.target.value); setQuote(null); }} /></label>
        </div>}
        <label>Instructions<textarea maxLength={1000} placeholder="Optional" value={guestInstructions} onChange={(event) => { setGuestInstructions(event.target.value); setQuote(null); }} /></label>
        <label>Promo code<input autoComplete="off" maxLength={80} value={promoCode} onChange={(event) => { setQuote(null); setPromoCode(event.target.value.toUpperCase()); }} /></label>
        {quote ? <div className="public-quote" aria-live="polite">
          <p><span>Subtotal</span><b>{formatMenuPriceMinor(quote.subtotal_minor, menu.currency_code)}</b></p>
          {quote.discount_minor !== "0" && <p><span>Discount</span><b>−{formatMenuPriceMinor(quote.discount_minor, menu.currency_code)}</b></p>}
          {quote.fulfillment_fee_minor !== "0" && <p><span>Delivery fee</span><b>{formatMenuPriceMinor(quote.fulfillment_fee_minor, menu.currency_code)}</b></p>}
          <p><span>Total</span><strong>{formatMenuPriceMinor(quote.total_minor, menu.currency_code)}</strong></p>
          <p><span>{quote.fulfillment_timing === "ASAP" ? "Promised" : "Scheduled"}</span><b>{minuteDateTime(quote.promised_at, fulfillmentOptions.timezone)}</b></p>
          <label>Name{location.guest_name_required && " (required)"}<input aria-required={location.guest_name_required} autoComplete="name" required={location.guest_name_required} maxLength={201} value={guestName} onChange={(event) => setGuestName(event.target.value)} /></label>
          {!station && <label>Phone{fulfillmentType === "PICKUP" && location.guest_phone_required_pickup && " (required)"}<input aria-required={fulfillmentType === "PICKUP" && location.guest_phone_required_pickup} autoComplete="tel" inputMode="tel" required={fulfillmentType === "PICKUP" && location.guest_phone_required_pickup} maxLength={32} value={guestPhone} onChange={(event) => setGuestPhone(event.target.value)} /></label>}
          <button type="button" className="primary-button" disabled={busy || !location.accepting_orders || missingRequiredGuest || missingFulfillment} onClick={() => void submit()}>{busy ? "Sending…" : "Send order"}</button>
        </div> : <button type="button" className="primary-button" disabled={busy || !location.accepting_orders || missingFulfillment} onClick={() => void getQuote()}>{busy ? "Checking…" : "Review total"}</button>}
      </>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <small><Clock3 aria-hidden="true" /> Prices, fees, and availability are confirmed by the restaurant.</small>
    </aside>
  </main>;
}

function VariantPicker({ currency, onAdd, variant }: { currency: string; onAdd: (optionIds: string[], optionNames: string[], note: string) => void; variant: PublicVariant }) {
  const groups = variant.modifier_groups;
  const [selected, setSelected] = useState(() => groups.flatMap((group) => group.options.filter((option) => option.is_default && option.is_available).map((option) => option.id)));
  const [note, setNote] = useState("");
  const selectedSet = new Set(selected);
  const valid = groups.every((group) => {
    const count = group.options.filter((option) => option.is_available && selectedSet.has(option.id)).length;
    return count >= group.min_selections && count <= group.max_selections;
  });
  const selectedOptions = groups.flatMap((group) => group.options).filter((option) => selectedSet.has(option.id));
  const price = selectedOptions.reduce((total, option) => total + BigInt(option.price_delta_minor), BigInt(variant.price_minor));

  function toggle(group: PublicModifierGroup, optionId: string, checked: boolean) {
    const groupIds = new Set(group.options.map((option) => option.id));
    setSelected((current) => {
      if (group.selection_type === "SINGLE") return checked ? [...current.filter((id) => !groupIds.has(id)), optionId] : current.filter((id) => id !== optionId);
      if (!checked) return current.filter((id) => id !== optionId);
      return current.filter((id) => groupIds.has(id)).length < group.max_selections ? [...current, optionId] : current;
    });
  }

  return <div className="public-variant"><div><span>{variant.name}</span><strong>{formatMenuPriceMinor(String(price), currency)}</strong></div>{groups.map((group) => <fieldset key={group.id}><legend>{group.name} <small>{group.min_selections ? `Choose ${group.min_selections}–${group.max_selections}` : "Optional"}</small></legend>{group.options.map((option) => <label className={!option.is_available ? "is-disabled" : ""} key={option.id}><input type={group.selection_type === "SINGLE" && group.min_selections > 0 ? "radio" : "checkbox"} name={`public-modifier-${variant.id}-${group.id}`} disabled={!option.is_available} checked={selectedSet.has(option.id)} onChange={(event) => toggle(group, option.id, event.target.checked)} /><span>{option.name}</span><small>{BigInt(option.price_delta_minor) === BigInt(0) ? "Included" : `+${formatMenuPriceMinor(option.price_delta_minor, currency)}`}</small></label>)}</fieldset>)}{groups.length > 0 && <label>Item note <input maxLength={500} placeholder="Optional" value={note} onChange={(event) => setNote(event.target.value)} /></label>}<button type="button" disabled={!valid} onClick={() => { onAdd(selected, selectedOptions.map((option) => option.name), note.trim()); setNote(""); }}><span>Add {variant.name}</span><strong>{formatMenuPriceMinor(String(price), currency)}</strong><Plus aria-hidden="true" /></button>{!valid && <small role="alert">Complete the required choices.</small>}</div>;
}

const messageOf = (error: unknown) => error instanceof Error ? error.message : "Something went wrong";
const isSlotConflict = (error: unknown) => error instanceof ApiError && error.status === 409 && error.code === "ONLINE_FULFILLMENT_SLOT_UNAVAILABLE";
const minuteTime = (value: string, timeZone?: string) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone });
const minuteDateTime = (value: string, timeZone?: string) => new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone });
const titleCase = (value: string) => value.toLowerCase().replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
const toQuoteItem = ({ client_item_id, variant_id, quantity, modifier_option_ids, note }: CartLine): OnlineQuoteItem => ({ client_item_id, variant_id, quantity, modifier_option_ids, note });
