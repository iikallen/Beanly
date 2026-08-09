"use client";

import {
  ChevronLeft,
  Clock3,
  Minus,
  Plus,
  Power,
  Search,
  ShoppingBag,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import {
  ApiError,
  api,
  type MenuProduct,
  type MenuReadModel,
  type PosRegister,
  type PosWarehouseChoice,
  type ProductVariant,
  type RegisterShift,
  type SalesOrder,
  type SalesOrderItem,
  type SalesOrderType,
} from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

type ConfigurationTarget = {
  product: MenuProduct;
  variant: ProductVariant;
  itemId?: string;
  clientItemId?: string;
};

export default function PosPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [registers, setRegisters] = useState<PosRegister[]>([]);
  const [warehouses, setWarehouses] = useState<PosWarehouseChoice[]>([]);
  const [menu, setMenu] = useState<MenuReadModel | null>(null);
  const [selectedRegisterId, setSelectedRegisterId] = useState("");
  const [selectedWarehouseId, setSelectedWarehouseId] = useState("");
  const [shift, setShift] = useState<RegisterShift | null>(null);
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [currentOrderId, setCurrentOrderId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [search, setSearch] = useState("");
  const [showOrders, setShowOrders] = useState(false);
  const [registerName, setRegisterName] = useState("");
  const [configuration, setConfiguration] = useState<ConfigurationTarget | null>(null);
  const [selectedOptionIds, setSelectedOptionIds] = useState<string[]>([]);
  const [cancelReason, setCancelReason] = useState("");
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pendingOrderId = useRef<string | null>(null);

  const organizationId = currentOrganization?.id;
  const locationId = currentLocation?.id;
  const currency = currentOrganization?.currency_code ?? "KZT";
  const canCreate = permissions.includes("sales.create");
  const canManageRegister = permissions.includes("sales.register.manage");
  const canManageShift = permissions.includes("sales.shift.manage");
  const canCancel = permissions.includes("sales.cancel");
  const currentOrder = orders.find((order) => order.id === currentOrderId) ?? null;
  const selectedRegister = registers.find((register) => register.id === selectedRegisterId);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (!accessToken || !organizationId || !locationId) return;
      setLoading(true);
      setError("");
      setPermissions([]);
      setShift(null);
      setOrders([]);
      setCurrentOrderId("");
      try {
        const [context, nextRegisters, nextMenu] = await Promise.all([
          api.getOrganizationContext(organizationId, accessToken),
          api.listPosRegisters(locationId, organizationId, accessToken),
          api.getMenu(locationId, organizationId, accessToken),
        ]);
        if (cancelled) return;
        setPermissions(context.permissions);
        setRegisters(nextRegisters.filter((register) => register.is_active));
        setMenu(nextMenu);
        setCategoryId(nextMenu.categories[0]?.id ?? "");
        setSelectedRegisterId((current) =>
          nextRegisters.some((register) => register.id === current && register.is_active)
            ? current
            : nextRegisters.find((register) => register.is_active)?.id ?? "",
        );
        try {
          const nextWarehouses = await api.listPosWarehouses(locationId, organizationId, accessToken);
          if (!cancelled) {
            const active = nextWarehouses.filter(
              (warehouse) => warehouse.location_id === locationId,
            );
            setWarehouses(active);
            setSelectedWarehouseId((current) =>
              active.some((warehouse) => warehouse.id === current)
                ? current
                : active[0]?.id ?? "",
            );
          }
        } catch {
          if (!cancelled) setWarehouses([]);
        }
      } catch (caught) {
        if (!cancelled) setError(messageOf(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, locationId, organizationId]);

  const loadOrders = useCallback(async (activeShift: RegisterShift) => {
    if (!accessToken || !organizationId) return;
    const nextOrders = await api.listSalesOrders(organizationId, accessToken, {
      shiftId: activeShift.id,
      status: "OPEN",
    });
    setOrders(nextOrders);
    setCurrentOrderId((current) =>
      nextOrders.some((order) => order.id === current) ? current : nextOrders[0]?.id ?? "",
    );
  }, [accessToken, organizationId]);

  useEffect(() => {
    let cancelled = false;
    async function loadShift() {
      await Promise.resolve();
      if (!accessToken || !organizationId || !selectedRegisterId) {
        setShift(null);
        return;
      }
      setError("");
      try {
        const current = await api.getCurrentRegisterShift(
          selectedRegisterId,
          organizationId,
          accessToken,
        );
        if (cancelled) return;
        setShift(current);
        if (current) {
          setSelectedWarehouseId(current.warehouse_id);
          await loadOrders(current);
        } else {
          setOrders([]);
          setCurrentOrderId("");
        }
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) {
          setShift(null);
          setOrders([]);
          setCurrentOrderId("");
        } else {
          setError(messageOf(caught));
        }
      }
    }
    void loadShift();
    return () => { cancelled = true; };
  }, [accessToken, loadOrders, organizationId, selectedRegisterId]);

  const products = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase();
    const category = menu?.categories.find((item) => item.id === categoryId);
    return (category?.products ?? []).filter((product) =>
      !normalized || product.name.toLocaleLowerCase().includes(normalized),
    );
  }, [categoryId, menu, search]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  function replaceOrder(order: SalesOrder) {
    setOrders((current) => {
      const exists = current.some((item) => item.id === order.id);
      return exists
        ? current.map((item) => item.id === order.id ? order : item)
        : [order, ...current];
    });
    setCurrentOrderId(order.id);
  }

  async function createRegister() {
    if (!accessToken || !organizationId || !locationId || !registerName.trim()) return;
    await run(async () => {
      const register = await api.createPosRegister(
        { location_id: locationId, name: registerName.trim() },
        organizationId,
        accessToken,
      );
      setRegisters((current) => [...current, register]);
      setSelectedRegisterId(register.id);
      setRegisterName("");
    });
  }

  async function openShift() {
    if (!accessToken || !organizationId || !selectedRegisterId || !selectedWarehouseId) return;
    await run(async () => {
      const opened = await api.openRegisterShift(
        { register_id: selectedRegisterId, warehouse_id: selectedWarehouseId },
        organizationId,
        accessToken,
      );
      setShift(opened);
      setOrders([]);
      setCurrentOrderId("");
    });
  }

  async function closeShift() {
    if (!accessToken || !organizationId || !shift) return;
    await run(async () => {
      await api.closeRegisterShift(shift.id, organizationId, accessToken);
      setShift(null);
      setOrders([]);
      setCurrentOrderId("");
    });
  }

  async function createOrder(type: SalesOrderType = "TAKEAWAY") {
    if (!accessToken || !organizationId || !shift) return;
    pendingOrderId.current ??= crypto.randomUUID();
    await run(async () => {
      const order = await api.createSalesOrder(
        { client_order_id: pendingOrderId.current!, shift_id: shift.id, order_type: type },
        organizationId,
        accessToken,
      );
      pendingOrderId.current = null;
      replaceOrder(order);
      setShowOrders(false);
    });
  }

  function openConfiguration(
    product: MenuProduct,
    variant: ProductVariant,
    item?: SalesOrderItem,
  ) {
    setConfiguration({
      product,
      variant,
      itemId: item?.id,
      clientItemId: item ? undefined : crypto.randomUUID(),
    });
    setSelectedOptionIds(
      item?.modifiers.map((modifier) => modifier.modifier_option_id)
        ?? variant.modifier_groups?.flatMap((group) =>
          group.options.filter((option) => option.is_default && option.is_available).map((option) => option.id),
        )
        ?? [],
    );
  }

  function chooseProduct(product: MenuProduct) {
    if (!currentOrder || !canCreate) return;
    const variants = product.variants.filter((variant) => variant.status === "ACTIVE");
    const variant = variants.find((item) => item.is_default) ?? variants[0];
    if (variant) openConfiguration(product, variant);
  }

  function switchVariant(variantId: string) {
    if (!configuration) return;
    const variant = configuration.product.variants.find((item) => item.id === variantId);
    if (!variant) return;
    setConfiguration({ ...configuration, variant });
    setSelectedOptionIds(
      variant.modifier_groups?.flatMap((group) =>
        group.options.filter((option) => option.is_default && option.is_available).map((option) => option.id),
      ) ?? [],
    );
  }

  function toggleOption(groupId: string, optionId: string, single: boolean, checked: boolean) {
    if (!configuration) return;
    const group = configuration.variant.modifier_groups?.find((item) => item.id === groupId);
    const groupOptionIds = new Set(group?.options.map((option) => option.id) ?? []);
    setSelectedOptionIds((current) => {
      if (single) return [...current.filter((id) => !groupOptionIds.has(id)), optionId];
      if (checked) {
        if (group && current.filter((id) => groupOptionIds.has(id)).length >= group.max_selections) {
          return current;
        }
        return [...current, optionId];
      }
      return current.filter((id) => id !== optionId);
    });
  }

  async function saveConfiguration() {
    if (!accessToken || !organizationId || !currentOrder || !configuration) return;
    await run(async () => {
      const order = configuration.itemId
        ? await api.configureSalesOrderItem(
          currentOrder.id,
          configuration.itemId,
          selectedOptionIds,
          organizationId,
          accessToken,
        )
        : await api.addSalesOrderItem(
          currentOrder.id,
          {
            client_item_id: configuration.clientItemId!,
            variant_id: configuration.variant.id,
            selected_option_ids: selectedOptionIds,
            quantity: 1,
          },
          organizationId,
          accessToken,
        );
      replaceOrder(order);
      setConfiguration(null);
    });
  }

  async function updateQuantity(item: SalesOrderItem, quantity: number) {
    if (!accessToken || !organizationId || !currentOrder || quantity < 1) return;
    await run(async () => replaceOrder(await api.updateSalesOrderItem(
      currentOrder.id,
      item.id,
      { quantity },
      organizationId,
      accessToken,
    )));
  }

  async function removeItem(itemId: string) {
    if (!accessToken || !organizationId || !currentOrder) return;
    await run(async () => replaceOrder(await api.removeSalesOrderItem(
      currentOrder.id,
      itemId,
      organizationId,
      accessToken,
    )));
  }

  async function cancelOrder() {
    if (!accessToken || !organizationId || !currentOrder) return;
    const reason = cancelReason.trim();
    if (!reason) return;
    await run(async () => {
      await api.cancelSalesOrder(currentOrder.id, reason.trim(), organizationId, accessToken);
      const remaining = orders.filter((order) => order.id !== currentOrder.id);
      setOrders(remaining);
      setCurrentOrderId(remaining[0]?.id ?? "");
      setShowCancelDialog(false);
      setCancelReason("");
    });
  }

  function openCancelDialog() {
    setCancelReason("");
    setShowCancelDialog(true);
  }

  function closeCancelDialog() {
    setShowCancelDialog(false);
    setCancelReason("");
  }

  function editItemConfiguration(item: SalesOrderItem) {
    if (!canCreate) return;
    const product = menu?.categories.flatMap((category) => category.products)
      .find((candidate) => candidate.id === item.product_id);
    const variant = product?.variants.find((candidate) => candidate.id === item.product_variant_id);
    if (product && variant) openConfiguration(product, variant, item);
  }

  if (loading) return <main className="loading-state">Loading POS…</main>;

  if (!canCreate && !canManageShift && !canManageRegister) {
    return <section className="pos-content"><div className="empty-state"><h1>POS access restricted</h1><p>Your role cannot create sales orders.</p></div></section>;
  }

  if (!shift) {
    return (
      <section className="pos-startup">
        <div className="pos-startup-card">
          <span className="pos-eyebrow">Beanly POS</span>
          <h1>Start selling</h1>
          <p>Choose a register and warehouse for {currentLocation?.name}.</p>
          {error && <p className="form-message error" role="alert">{error}</p>}
          <label className="modal-field">
            <span>Register</span>
            <select value={selectedRegisterId} onChange={(event) => setSelectedRegisterId(event.target.value)}>
              <option value="">Select register</option>
              {registers.map((register) => <option key={register.id} value={register.id}>{register.name}</option>)}
            </select>
          </label>
          {canManageRegister && (
            <div className="pos-inline-create">
              <input
                aria-label="New register name"
                placeholder="New register name"
                value={registerName}
                onChange={(event) => setRegisterName(event.target.value)}
              />
              <button className="secondary-button" disabled={busy || !registerName.trim()} type="button" onClick={createRegister}>Create</button>
            </div>
          )}
          <label className="modal-field">
            <span>Warehouse</span>
            <select value={selectedWarehouseId} onChange={(event) => setSelectedWarehouseId(event.target.value)}>
              <option value="">Select warehouse</option>
              {warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
            </select>
          </label>
          {warehouses.length === 0 && <p className="pos-hint">No accessible active warehouse is available for this location.</p>}
          <button className="primary-button pos-open-shift" disabled={busy || !canManageShift || !selectedRegisterId || !selectedWarehouseId} type="button" onClick={openShift}>
            <Power aria-hidden="true" /> {busy ? "Opening…" : "Open shift"}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="pos-content">
      <header className="pos-header">
        <div>
          <span className="pos-eyebrow">{currentLocation?.name} · {selectedRegister?.name}</span>
          <strong><Clock3 aria-hidden="true" /> Shift opened {formatTime(shift.opened_at)}</strong>
        </div>
        <div className="pos-header-actions">
          <button className="secondary-button" type="button" onClick={() => setShowOrders((current) => !current)}>Orders ({orders.length})</button>
          <button className="secondary-button" disabled={busy || orders.length > 0} type="button" onClick={closeShift}>Close shift</button>
        </div>
      </header>
      {error && <p className="pos-global-error" role="alert">{error}</p>}

      <div className="pos-grid">
        <aside className={showOrders ? "pos-orders-drawer is-open" : "pos-orders-drawer"}>
          <div className="pos-panel-title">
            <button className="icon-button" type="button" aria-label="Hide orders" onClick={() => setShowOrders(false)}><ChevronLeft /></button>
            <h2>Open orders</h2>
          </div>
          <button className="primary-button" disabled={busy || !canCreate} type="button" onClick={() => createOrder()}>+ New order</button>
          <div className="pos-order-list">
            {orders.map((order) => (
              <button className={order.id === currentOrderId ? "is-active" : ""} key={order.id} type="button" onClick={() => { setCurrentOrderId(order.id); setShowOrders(false); }}>
                <span><strong>#{order.number}</strong>{prettyOrderType(order.order_type)}</span>
                <b>{formatMenuPriceMinor(order.total_minor, order.currency_code)}</b>
              </button>
            ))}
            {orders.length === 0 && <p>No open orders.</p>}
          </div>
        </aside>

        <div className="pos-catalog">
          <div className="pos-catalog-toolbar">
            <div className="pos-category-tabs" role="tablist" aria-label="Menu categories">
              {menu?.categories.map((category) => (
                <button className={category.id === categoryId ? "is-active" : ""} key={category.id} role="tab" aria-selected={category.id === categoryId} type="button" onClick={() => setCategoryId(category.id)}>{category.name}</button>
              ))}
            </div>
            <label className="pos-search"><Search aria-hidden="true" /><span className="sr-only">Search products</span><input placeholder="Search products" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          </div>
          {!currentOrder ? (
            <div className="pos-empty-order">
              <ShoppingBag aria-hidden="true" />
              <h2>Create or select an order</h2>
              <p>Every change is saved to the server immediately.</p>
              <button className="primary-button" disabled={busy || !canCreate} type="button" onClick={() => createOrder()}>Create order</button>
            </div>
          ) : (
            <div className="pos-product-grid">
              {products.map((product) => {
                const activeVariants = product.variants.filter((variant) => variant.status === "ACTIVE");
                const from = activeVariants.reduce<string | null>((lowest, variant) => lowest === null || BigInt(variant.effective_price_minor) < BigInt(lowest) ? variant.effective_price_minor : lowest, null);
                return (
                  <button disabled={busy || !canCreate || !activeVariants.length} key={product.id} type="button" onClick={() => chooseProduct(product)}>
                    <span className="pos-product-icon" aria-hidden="true">{product.name.charAt(0)}</span>
                    <strong>{product.name}</strong>
                    <small>{activeVariants.length > 1 ? `${activeVariants.length} variants · ` : ""}{from ? formatMenuPriceMinor(from, currency) : "Unavailable"}</small>
                  </button>
                );
              })}
              {products.length === 0 && <div className="empty-state"><h2>No products</h2><p>This category has no available products.</p></div>}
            </div>
          )}
        </div>

        <aside className="pos-receipt">
          {currentOrder ? (
            <>
              <div className="pos-receipt-heading">
                <div><span>Current order</span><h2>Order #{currentOrder.number}</h2></div>
                <select aria-label="Order type" disabled={busy || !canCreate} value={currentOrder.order_type} onChange={(event) => run(async () => replaceOrder(await api.updateSalesOrder(currentOrder.id, { order_type: event.target.value as SalesOrderType }, organizationId!, accessToken!)))}>
                  <option value="DINE_IN">Dine-in</option><option value="TAKEAWAY">Takeaway</option><option value="DELIVERY">Delivery</option>
                </select>
              </div>
              <div className="pos-receipt-items">
                {currentOrder.items.map((item) => (
                  <article key={item.id}>
                    <div className="pos-line-main">
                      <div><strong>{item.product_name}</strong><span>{item.variant_name}</span></div>
                      <b>{formatMenuPriceMinor(item.line_total_minor, currentOrder.currency_code)}</b>
                    </div>
                    {item.modifiers.length > 0 && <p>{item.modifiers.map((modifier) => modifier.modifier_option_name).join(" · ")}</p>}
                    {item.note && <p>{item.note}</p>}
                    <div className="pos-line-actions">
                      <span className="pos-quantity"><button aria-label={`Decrease ${item.product_name}`} disabled={busy || !canCreate || item.quantity <= 1} type="button" onClick={() => updateQuantity(item, item.quantity - 1)}><Minus /></button><b>{item.quantity}</b><button aria-label={`Increase ${item.product_name}`} disabled={busy || !canCreate} type="button" onClick={() => updateQuantity(item, item.quantity + 1)}><Plus /></button></span>
                      <button disabled={busy || !canCreate} type="button" onClick={() => editItemConfiguration(item)}>Customize</button>
                      <button className="danger-link" aria-label={`Remove ${item.product_name}`} disabled={busy || !canCreate} type="button" onClick={() => removeItem(item.id)}><Trash2 /></button>
                    </div>
                  </article>
                ))}
                {currentOrder.items.length === 0 && <div className="pos-receipt-empty"><ShoppingBag aria-hidden="true" /><p>Add a product to start this order.</p></div>}
              </div>
              <div className="pos-receipt-total"><span>Total</span><strong>{formatMenuPriceMinor(currentOrder.total_minor, currentOrder.currency_code)}</strong></div>
              <button className="primary-button pos-pay-button" disabled type="button">Pay · Stage 11</button>
              {canCancel && <button className="pos-cancel-order" disabled={busy} type="button" onClick={openCancelDialog}>Cancel order</button>}
            </>
          ) : (
            <div className="pos-receipt-empty"><ShoppingBag aria-hidden="true" /><h2>No order selected</h2></div>
          )}
        </aside>
      </div>

      {configuration && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card pos-config-modal" role="dialog" aria-modal="true" aria-labelledby="pos-config-title">
            <button className="modal-close" type="button" aria-label="Close customization" onClick={() => setConfiguration(null)}><X /></button>
            <span className="pos-eyebrow">Customize</span>
            <h2 id="pos-config-title">{configuration.product.name}</h2>
            {!configuration.itemId && configuration.product.variants.filter((variant) => variant.status === "ACTIVE").length > 1 && (
              <label className="modal-field"><span>Variant</span><select value={configuration.variant.id} onChange={(event) => switchVariant(event.target.value)}>{configuration.product.variants.filter((variant) => variant.status === "ACTIVE").map((variant) => <option key={variant.id} value={variant.id}>{variant.name} · {formatMenuPriceMinor(variant.effective_price_minor, currency)}</option>)}</select></label>
            )}
            <div className="pos-modifier-groups">
              {configuration.variant.modifier_groups?.filter((group) => group.is_active).map((group) => (
                <fieldset key={group.id}>
                  <legend><span>{group.name}</span><small>{group.min_selections === 0 ? "Optional" : `Choose ${group.min_selections}${group.max_selections !== group.min_selections ? `–${group.max_selections}` : ""}`}</small></legend>
                  {group.options.map((option) => (
                    <label className={!option.is_available ? "is-disabled" : ""} key={option.id}>
                      <input type={group.selection_type === "SINGLE" ? "radio" : "checkbox"} name={`modifier-${group.id}`} disabled={!option.is_available} checked={selectedOptionIds.includes(option.id)} onChange={(event) => toggleOption(group.id, option.id, group.selection_type === "SINGLE", event.target.checked)} />
                      <span>{option.name}</span>
                      <b>{BigInt(option.effective_price_delta_minor) === BigInt(0) ? "Included" : `+${formatMenuPriceMinor(option.effective_price_delta_minor, currency)}`}</b>
                    </label>
                  ))}
                </fieldset>
              ))}
            </div>
            {!configurationIsValid(configuration.variant, selectedOptionIds) && <p className="form-message error" role="alert">Complete the required modifier selections.</p>}
            <div className="modal-actions"><button className="secondary-button" type="button" onClick={() => setConfiguration(null)}>Cancel</button><button className="primary-button" disabled={busy || !configurationIsValid(configuration.variant, selectedOptionIds)} type="button" onClick={saveConfiguration}>{busy ? "Saving…" : `${configuration.itemId ? "Update" : "Add"} · ${formatMenuPriceMinor(configurationPrice(configuration.variant, selectedOptionIds), currency)}`}</button></div>
          </div>
        </div>
      )}
      {showCancelDialog && currentOrder && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card pos-cancel-modal" role="dialog" aria-modal="true" aria-labelledby="pos-cancel-title" onKeyDown={(event) => { if (event.key === "Escape") closeCancelDialog(); }}>
            <button className="modal-close" type="button" aria-label="Close cancellation" onClick={closeCancelDialog}><X /></button>
            <span className="pos-eyebrow">Order #{currentOrder.number}</span>
            <h2 id="pos-cancel-title">Cancel order?</h2>
            <p>The order will remain in the audit history and cannot be edited.</p>
            <label className="modal-field"><span>Reason</span><input autoFocus maxLength={1000} placeholder="Customer cancelled" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} /></label>
            <div className="modal-actions"><button className="secondary-button" type="button" onClick={closeCancelDialog}>Keep order</button><button className="danger-button" disabled={busy || !cancelReason.trim()} type="button" onClick={cancelOrder}>{busy ? "Cancelling…" : "Cancel order"}</button></div>
          </div>
        </div>
      )}
    </section>
  );
}

function configurationPrice(variant: ProductVariant, selectedOptionIds: string[]) {
  return String((variant.modifier_groups ?? []).flatMap((group) => group.options)
    .filter((option) => selectedOptionIds.includes(option.id))
    .reduce((total, option) => total + BigInt(option.effective_price_delta_minor), BigInt(variant.effective_price_minor)));
}

function configurationIsValid(variant: ProductVariant, selectedOptionIds: string[]) {
  const selected = new Set(selectedOptionIds);
  return (variant.modifier_groups ?? []).filter((group) => group.is_active).every((group) => {
    const count = group.options.filter((option) => option.is_available && selected.has(option.id)).length;
    return count >= group.min_selections && count <= group.max_selections;
  });
}

function prettyOrderType(value: SalesOrderType) {
  if (value === "DINE_IN") return "Dine-in";
  if (value === "DELIVERY") return "Delivery";
  return "Takeaway";
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
