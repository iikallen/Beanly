"use client";

import {
  ChevronLeft,
  Clock3,
  CreditCard,
  Minus,
  Plus,
  Power,
  Search,
  ShieldAlert,
  ShoppingBag,
  Tags,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ConnectionStatus } from "@/components/pos/connection-status";
import { CashDrawerControls } from "@/components/pos/cash-drawer";
import { OfflineReady } from "@/components/pos/offline-ready";
import { SyncStatus } from "@/components/pos/sync-status";
import { useWorkspace } from "@/components/workspace-provider";
import { useOfflinePos } from "@/hooks/use-offline-pos";
import {
  ApiError,
  api,
  type CashDrawer,
  type Customer,
  type CustomerLoyalty,
  type MenuProduct,
  type MenuReadModel,
  type ExternalPaymentAttempt,
  type PaymentMethod,
  type PaymentMethodChoice,
  type PosRegister,
  type PosWarehouseChoice,
  type Promotion,
  type LoyaltyQuote,
  type ProductVariant,
  type RegisterShift,
  type SalesOrderType,
  type TerminalBinding,
} from "@/lib/api";
import { formatMenuPriceMinor, parseMenuPriceToMinor, priceMinorToInput } from "@/lib/menu";
import {
  currentOfflineSession,
  defaultPaymentMethods,
  OfflineApiError,
  pairDevice,
  refreshOfflineSession,
  revokeDevice,
  startOfflineSession,
  type SessionShell,
} from "@/lib/offline/api";
import { readCatalog, readCurrentSession, saveSession } from "@/lib/offline/db";
import {
  cancelLocalOrder,
  createLocalOrder,
  markExternalPaymentApproved,
  applyServerPricing,
  payLocalOrder,
  updateLocalOrder,
} from "@/lib/offline/orders";
import { buildLocalItem, catalogSelectionIsValid } from "@/lib/offline/catalog";
import type { OfflineOrder, OfflineOrderItem, OfflineSession } from "@/lib/offline/types";
import { paymentRequest, type PaymentMode } from "@/lib/payment";
import { paymentAttemptAction, terminalStatusCopy } from "@/lib/fiscal-live";

type ConfigurationTarget = {
  product: MenuProduct;
  variant: ProductVariant;
  itemId?: string;
  clientItemId?: string;
};

type CompletedLocalPayment = {
  amount_minor: string;
  currency_code: string;
  origin: "LOCAL" | "TERMINAL";
  lines: Array<{ method: PaymentMethod; change_minor: string }>;
};

export default function PosPage() {
  const { accessToken, user } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [registers, setRegisters] = useState<PosRegister[]>([]);
  const [warehouses, setWarehouses] = useState<PosWarehouseChoice[]>([]);
  const [menu, setMenu] = useState<MenuReadModel | null>(null);
  const [selectedRegisterId, setSelectedRegisterId] = useState("");
  const [selectedWarehouseId, setSelectedWarehouseId] = useState("");
  const [shift, setShift] = useState<RegisterShift | null>(null);
  const [drawer, setDrawer] = useState<CashDrawer | null>(null);
  const [offlineSession, setOfflineSession] = useState<OfflineSession | null>(null);
  const [menuCatalogId, setMenuCatalogId] = useState("");
  const [currentOrderId, setCurrentOrderId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [search, setSearch] = useState("");
  const [showOrders, setShowOrders] = useState(false);
  const [showDiscounts, setShowDiscounts] = useState(false);
  const [showCustomers, setShowCustomers] = useState(false);
  const [customerSearch, setCustomerSearch] = useState("");
  const [customerResults, setCustomerResults] = useState<Customer[]>([]);
  const [attachedCustomer, setAttachedCustomer] = useState<Customer | null>(null);
  const [customerLoyalty, setCustomerLoyalty] = useState<CustomerLoyalty | null>(null);
  const [loyaltyPoints, setLoyaltyPoints] = useState("");
  const [loyaltyQuote, setLoyaltyQuote] = useState<LoyaltyQuote | null>(null);
  const [newCustomerPhone, setNewCustomerPhone] = useState("");
  const [newCustomerName, setNewCustomerName] = useState("");
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [promoCode, setPromoCode] = useState("");
  const [customType, setCustomType] = useState<"PERCENT" | "FIXED_AMOUNT">("PERCENT");
  const [customValue, setCustomValue] = useState("");
  const [customReason, setCustomReason] = useState("");
  const [registerName, setRegisterName] = useState("");
  const [startingCash, setStartingCash] = useState("0");
  const [configuration, setConfiguration] = useState<ConfigurationTarget | null>(null);
  const [selectedOptionIds, setSelectedOptionIds] = useState<string[]>([]);
  const [configurationNote, setConfigurationNote] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [paymentOrder, setPaymentOrder] = useState<OfflineOrder | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethodChoice[]>([]);
  const [paymentMode, setPaymentMode] = useState<PaymentMode>(null);
  const [paymentCashReceived, setPaymentCashReceived] = useState("");
  const [splitCash, setSplitCash] = useState("");
  const [splitCard, setSplitCard] = useState("");
  const [splitOther, setSplitOther] = useState("");
  const [paymentReference, setPaymentReference] = useState("");
  const [completedPayment, setCompletedPayment] = useState<CompletedLocalPayment | null>(null);
  const [paymentCustomerName, setPaymentCustomerName] = useState<string | null>(null);
  const [cardConfirmed, setCardConfirmed] = useState(false);
  const [paymentBusy, setPaymentBusy] = useState(false);
  const [paymentError, setPaymentError] = useState("");
  const [terminalBindings, setTerminalBindings] = useState<TerminalBinding[]>([]);
  const [terminalSelected, setTerminalSelected] = useState(false);
  const [terminalMethod, setTerminalMethod] = useState<"CARD" | "QR">("CARD");
  const [terminalAttempt, setTerminalAttempt] = useState<ExternalPaymentAttempt | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [clockNow, setClockNow] = useState(0);
  const pendingPayment = useRef<{ id: string; payload: string } | null>(null);
  const pendingShiftOpen = useRef<{ id: string; payload: string } | null>(null);
  const pendingTerminal = useRef<{ id: string; fingerprint: string } | null>(null);
  const pendingRedemption = useRef<{ id: string; payload: string } | null>(null);

  const offline = useOfflinePos(offlineSession);

  const organizationId = currentOrganization?.id ?? offlineSession?.organization_id;
  const locationId = currentLocation?.id ?? offlineSession?.location_id;
  const currency = currentOrganization?.currency_code ?? offlineSession?.shell.currency_code ?? "KZT";
  const canCreate = permissions.includes("sales.create");
  const canManageRegister = permissions.includes("sales.register.manage");
  const canManageShift = permissions.includes("sales.shift.manage");
  const canManageDevice = permissions.includes("pos.device.manage");
  const canCancel = permissions.includes("sales.cancel");
  const canPay = permissions.includes("payments.create");
  const canReadRefunds = permissions.includes("sales.read") && permissions.includes("payments.read");
  const canApplyDiscount = permissions.includes("discounts.apply");
  const canOverrideDiscount = permissions.includes("discounts.override");
  const canReadCustomers = permissions.includes("customers.read");
  const canWriteCustomers = permissions.includes("customers.write");
  const canReadLoyalty = permissions.includes("loyalty.read");
  const canRedeemLoyalty = permissions.includes("loyalty.redeem");
  const orders = offline.orders.filter((order) => !order.status.startsWith("SYNCED_CANCELLED") && !order.status.startsWith("SYNCED_PAID"));
  const selectedOrder = orders.find((order) => order.id === currentOrderId)
    ?? orders.find((order) => order.status === "OPEN" || order.status === "SYNCED_OPEN")
    ?? null;
  const currentOrder = selectedOrder && (selectedOrder.status === "OPEN" || selectedOrder.status === "SYNCED_OPEN") ? selectedOrder : null;
  const loyaltyReserved = Boolean(currentOrder?.discounts.some(isLoyaltyDiscount));
  const selectedRegister = registers.find((register) => register.id === selectedRegisterId);
  const hasOpenOrders = orders.some((order) => order.status === "OPEN" || order.status === "SYNCED_OPEN");
  const sessionActive = Boolean(offlineSession && offlineSession.status === "ACTIVE" && clockNow + offlineSession.clock_offset_ms < Date.parse(offlineSession.expires_at));
  const canWriteLocal = sessionActive && offline.isWriter && shift?.status === "OPEN" && drawer?.status !== "CLOSING" && drawer?.status !== "CLOSED";
  const terminalBinding = terminalBindings.find((binding) => binding.is_active) ?? null;
  const canMutateCurrent = canCreate && canWriteLocal && !loyaltyReserved;

  useEffect(() => {
    const tick = () => setClockNow(Date.now());
    queueMicrotask(tick);
    const interval = window.setInterval(tick, 30_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      setLoading(true);
      const cached = await readCurrentSession().catch(() => null);
      const cachedUsable = Boolean(cached
        && (cached.status === "ACTIVE" || cached.status === "EXPIRED")
        && (!organizationId || cached.organization_id === organizationId)
        && (!locationId || cached.location_id === locationId));
      if (!cancelled && cached && cachedUsable) {
        setOfflineSession(cached);
        setPermissions(cached.shell.permissions);
        setPaymentMethods(cached.shell.payment_methods.length ? cached.shell.payment_methods : defaultPaymentMethods());
        setMenu(cached.catalog_snapshot.public_payload);
        setMenuCatalogId(cached.catalog_snapshot_id);
        setCategoryId(cached.catalog_snapshot.public_payload.categories[0]?.id ?? "");
        setSelectedRegisterId(cached.register_id);
        setSelectedWarehouseId(cached.warehouse_id);
        setShift(shiftFromSession(cached));
        setDrawer(null);
      }
      if (!accessToken) {
        if (!cancelled) setLoading(false);
        return;
      }
      if (!organizationId || !locationId) {
        setLoading(false);
        return;
      }
      setError("");
      if (!cachedUsable) {
        setPermissions([]);
        setShift(null);
        setDrawer(null);
      }
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
        if (!cachedUsable) {
          setMenu(nextMenu);
          setCategoryId(nextMenu.categories[0]?.id ?? "");
        }
        setSelectedRegisterId((current) =>
          nextRegisters.some((register) => register.id === current && register.is_active)
            ? current
            : nextRegisters.find((register) => register.is_active)?.id ?? "",
        );
        const nextPaymentMethods = context.permissions.includes("payments.create")
          ? await api.listPaymentMethods(organizationId, accessToken)
          : [];
        if (cancelled) return;
        setPaymentMethods(nextPaymentMethods);
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

  useEffect(() => {
    let cancelled = false;
    async function loadTerminalBindings() {
      await Promise.resolve();
      if (!accessToken || !organizationId || !selectedRegisterId || offline.networkStatus !== "ONLINE" || !canPay) {
        setTerminalBindings([]);
        return;
      }
      try {
        const values = await api.listTerminalBindings(selectedRegisterId, organizationId, accessToken);
        if (!cancelled) setTerminalBindings(values);
      } catch {
        if (!cancelled) setTerminalBindings([]);
      }
    }
    void loadTerminalBindings();
    return () => { cancelled = true; };
  }, [accessToken, canPay, offline.networkStatus, organizationId, selectedRegisterId]);

  useEffect(() => {
    let cancelled = false;
    async function loadPromotions() {
      if (!accessToken || !organizationId || !canApplyDiscount || offline.networkStatus !== "ONLINE") return setPromotions([]);
      try {
        const values = await api.listPromotions(organizationId, accessToken);
        if (!cancelled) setPromotions(values.filter((value) => value.status === "ACTIVE"));
      } catch { if (!cancelled) setPromotions([]); }
    }
    void loadPromotions();
    return () => { cancelled = true; };
  }, [accessToken, canApplyDiscount, offline.networkStatus, organizationId]);

  useEffect(() => {
    let cancelled = false;
    function clearCustomerState() {
      setAttachedCustomer(null); setCustomerLoyalty(null); setCustomerResults([]); setCustomerSearch("");
      setLoyaltyPoints(""); setLoyaltyQuote(null); setNewCustomerPhone(""); setNewCustomerName(""); setShowCustomers(false);
      pendingRedemption.current = null;
    }
    async function loadCustomer() {
      if (!accessToken || !organizationId || !currentOrder?.server_order_id || offline.networkStatus !== "ONLINE" || !canReadCustomers) {
        if (!cancelled) clearCustomerState();
        return;
      }
      clearCustomerState();
      try {
        const order = await api.getSalesOrder(currentOrder.server_order_id, organizationId, accessToken);
        if (cancelled) return;
        if (!order.customer_id) { setAttachedCustomer(null); setCustomerLoyalty(null); return; }
        const [customer, balance] = await Promise.all([
          api.getCustomer(order.customer_id, organizationId, accessToken),
          canReadLoyalty ? api.getCustomerLoyalty(order.customer_id, organizationId, accessToken) : Promise.resolve(null),
        ]);
        if (!cancelled) { setAttachedCustomer(customer); setCustomerLoyalty(balance); }
      } catch { if (!cancelled) { setAttachedCustomer(null); setCustomerLoyalty(null); } }
    }
    void loadCustomer();
    return () => { cancelled = true; };
  }, [accessToken, canReadCustomers, canReadLoyalty, currentOrder?.server_order_id, offline.networkStatus, organizationId]);

  useEffect(() => {
    let cancelled = false;
    async function loadShift() {
      await Promise.resolve();
      if (!accessToken || !organizationId || !selectedRegisterId) return;
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
          const currentDrawer = await api.getCurrentCashDrawer(selectedRegisterId, organizationId, accessToken);
          if (cancelled) return;
          setDrawer(currentDrawer);
          setSelectedWarehouseId(current.warehouse_id);
          const register = registers.find((item) => item.id === current.register_id);
          const shell: SessionShell = {
            organization_name: currentOrganization?.name ?? "Beanly",
            location_name: currentLocation?.name ?? "POS",
            location_timezone: currentLocation?.timezone ?? "UTC",
            register_name: register?.name ?? "Register",
            operator_name: user ? `${user.first_name} ${user.last_name}` : "Cashier",
            currency_code: currency,
            permissions,
            payment_methods: paymentMethods.length ? paymentMethods : defaultPaymentMethods(),
          };
          const cached = await currentOfflineSession(shell).catch(() => null);
          if (cancelled) return;
          if (cached?.shift_id === current.id) {
            await saveSession(cached);
            if (cancelled) return;
            setOfflineSession(cached);
            setMenu(cached.catalog_snapshot.public_payload);
            setMenuCatalogId(cached.catalog_snapshot_id);
            setCategoryId(cached.catalog_snapshot.public_payload.categories[0]?.id ?? "");
          }
        } else {
          setDrawer(null);
          setOfflineSession(null);
          setCurrentOrderId("");
        }
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) {
          setShift(null);
          setDrawer(null);
          setOfflineSession(null);
          setCurrentOrderId("");
        } else {
          setError(messageOf(caught));
        }
      }
    }
    void loadShift();
    return () => { cancelled = true; };
  }, [accessToken, currency, currentLocation?.name, currentLocation?.timezone, currentOrganization?.name, organizationId, paymentMethods, permissions, registers, selectedRegisterId, user]);

  useEffect(() => {
    let cancelled = false;
    const snapshotId = currentOrder?.catalog_snapshot_id ?? offlineSession?.catalog_snapshot_id;
    if (!snapshotId || snapshotId === menuCatalogId) return;
    readCatalog(snapshotId).then((snapshot) => {
      if (cancelled || !snapshot) return;
      setMenu(snapshot.public_payload);
      setMenuCatalogId(snapshot.id);
      setCategoryId((current) => snapshot.public_payload.categories.some((category) => category.id === current)
        ? current
        : snapshot.public_payload.categories[0]?.id ?? "");
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [currentOrder?.catalog_snapshot_id, menuCatalogId, offlineSession?.catalog_snapshot_id]);

  useEffect(() => {
    if (!accessToken || !offlineSession || offline.networkStatus !== "ONLINE") return;
    let cancelled = false;
    const refresh = async () => {
      const next = await refreshOfflineSession(offlineSession.id, offlineSession.shell);
      await saveSession(next);
      if (!cancelled) setOfflineSession(next);
    };
    const onFocus = () => { if (document.visibilityState === "visible") void refresh().catch(() => undefined); };
    const interval = window.setInterval(() => { void refresh().catch(() => undefined); }, 120_000);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [accessToken, offline.networkStatus, offlineSession]);

  const products = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase();
    const category = menu?.categories.find((item) => item.id === categoryId);
    return (category?.products ?? []).filter((product) =>
      !normalized || product.name.toLocaleLowerCase().includes(normalized),
    );
  }, [categoryId, menu, search]);

  const paymentDraft = useMemo(() => paymentRequest({
    mode: paymentMode,
    totalMinor: paymentOrder?.total_minor ?? "0",
    cashMinor: paymentInputMinor(splitCash),
    cashReceivedMinor: paymentCashReceived.trim()
      ? parseMenuPriceToMinor(paymentCashReceived)
      : null,
    cardMinor: paymentInputMinor(splitCard),
    otherMinor: paymentInputMinor(splitOther),
    otherReference: paymentReference,
  }), [paymentCashReceived, paymentMode, paymentOrder?.total_minor, paymentReference, splitCard, splitCash, splitOther]);
  const paymentMethodNames = useMemo(
    () => new Map(paymentMethods.map((method) => [method.code, method.name])),
    [paymentMethods],
  );
  const manualPromotionChoices = useMemo(() => offline.networkStatus === "ONLINE"
    ? promotions.filter((promotion) => promotion.application_mode === "MANUAL").map((promotion) => ({ id: promotion.id, name: promotion.pos_name, kind: promotion.discount_kind, percent: promotion.percent_rate, requiresOverride: promotion.requires_override_permission }))
    : (menu?.promotions ?? []).filter((promotion) => promotion.application_mode === "MANUAL").map((promotion) => ({ id: promotion.promotion_id, name: promotion.name, kind: promotion.kind, percent: promotion.percent_rate, requiresOverride: promotion.requires_override_permission ?? true })), [menu?.promotions, offline.networkStatus, promotions]);
  const needsSettlementConfirmation = paymentDraft.lines.some((line) => line.method === "CARD" || line.method === "OTHER");
  const terminalOrderReady = paymentOrder?.status === "SYNCED_OPEN"
    && Boolean(paymentOrder.server_order_id)
    && paymentOrder.revision === paymentOrder.last_synced_revision
    && offline.networkStatus === "ONLINE"
    && canWriteLocal;
  const terminalAction = terminalAttempt ? paymentAttemptAction(terminalAttempt.status) : "START";

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

  async function afterLocalWrite(order: OfflineOrder) {
    setCurrentOrderId(order.id);
    await offline.reload();
    void offline.syncNow();
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
    const startingCashMinor = parseMenuPriceToMinor(startingCash);
    if (!startingCashMinor) return;
    const openPayload = `${selectedRegisterId}|${selectedWarehouseId}|${startingCashMinor}`;
    if (pendingShiftOpen.current?.payload !== openPayload) pendingShiftOpen.current = { id: crypto.randomUUID(), payload: openPayload };
    await run(async () => {
      const opened = await api.openRegisterShift(
        {
          register_id: selectedRegisterId,
          warehouse_id: selectedWarehouseId,
          starting_cash_minor: startingCashMinor,
          client_open_id: pendingShiftOpen.current!.id,
        },
        organizationId,
        accessToken,
      );
      setShift(opened);
      if (opened.drawer_session_id) setDrawer(await api.getCashDrawer(opened.drawer_session_id, organizationId, accessToken));
      pendingShiftOpen.current = null;
      setOfflineSession(null);
      setCurrentOrderId("");
    });
  }

  async function enableOffline() {
    if (!accessToken || !organizationId || !shift || !selectedRegister) return;
    await run(async () => {
      const shell: SessionShell = {
        organization_name: currentOrganization?.name ?? "Beanly",
        location_name: currentLocation?.name ?? "POS",
        register_name: selectedRegister.name,
        operator_name: user ? `${user.first_name} ${user.last_name}` : "Cashier",
        currency_code: currency,
        permissions,
        payment_methods: paymentMethods.length ? paymentMethods : defaultPaymentMethods(),
      };
      let session: OfflineSession;
      try {
        session = await startOfflineSession(shift.id, organizationId, accessToken, shell);
      } catch (caught) {
        if (!canManageDevice || !(caught instanceof OfflineApiError) || ![401, 404].includes(caught.status)) throw caught;
        await pairDevice(selectedRegister.id, `${selectedRegister.name} POS`, organizationId, accessToken);
        session = await startOfflineSession(shift.id, organizationId, accessToken, shell);
      }
      await saveSession(session);
      setOfflineSession(session);
      setMenu(session.catalog_snapshot.public_payload);
      setMenuCatalogId(session.catalog_snapshot_id);
      setCategoryId(session.catalog_snapshot.public_payload.categories[0]?.id ?? "");
      await offline.requestPersistence();
      await offline.reload();
    });
  }

  async function markCashCloseStarted() {
    if (offlineSession?.status !== "ACTIVE") return;
    const closed = { ...offlineSession, status: "CLOSED" as const };
    await saveSession(closed).catch(() => undefined);
    setOfflineSession(closed);
  }

  function finishCashClose() {
    setShift(null);
    setDrawer(null);
    setOfflineSession(null);
    setCurrentOrderId("");
  }

  async function disableOffline() {
    if (!accessToken || !organizationId || !offlineSession || !canManageDevice || hasOpenOrders || offline.unresolvedCount > 0) return;
    await run(async () => {
      await revokeDevice(offlineSession.device_id, organizationId, accessToken);
      await saveSession({ ...offlineSession, status: "REVOKED" });
      setOfflineSession(null);
    });
  }

  async function createOrder(type: SalesOrderType = "TAKEAWAY") {
    if (!offlineSession || !canWriteLocal) return;
    await run(async () => {
      await afterLocalWrite(await createLocalOrder(offlineSession, type));
      setShowOrders(false);
    });
  }

  function openConfiguration(
    product: MenuProduct,
    variant: ProductVariant,
    item?: OfflineOrderItem,
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
    setConfigurationNote(item?.note ?? "");
  }

  function chooseProduct(product: MenuProduct) {
    if (!currentOrder || menuCatalogId !== currentOrder.catalog_snapshot_id || !canMutateCurrent || product.is_available === false || product.is_visible === false) return;
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
    if (!currentOrder || !configuration || !offlineSession || !canMutateCurrent) return;
    await run(async () => {
      if (!catalogSelectionIsValid(configuration.product, configuration.variant, selectedOptionIds)) {
        throw new Error("This product configuration is no longer available in the cached catalog");
      }
      const previous = currentOrder.items.find((item) => item.id === configuration.itemId);
      const item = buildLocalItem(
        configuration.product,
        configuration.variant,
        selectedOptionIds,
        previous?.client_item_id ?? configuration.clientItemId!,
        previous?.quantity ?? 1,
        configurationNote.trim() || null,
      );
      const order = await updateLocalOrder(currentOrder.id, (value) => {
        value.items = previous
          ? value.items.map((candidate) => candidate.id === previous.id ? item : candidate)
          : [...value.items, item];
      }, offlineSession.clock_offset_ms);
      await afterLocalWrite(order);
      setConfiguration(null);
    });
  }

  async function updateQuantity(item: OfflineOrderItem, quantity: number) {
    if (!currentOrder || !offlineSession || !canMutateCurrent || quantity < 1) return;
    await run(async () => afterLocalWrite(await updateLocalOrder(currentOrder.id, (order) => {
      const target = order.items.find((candidate) => candidate.id === item.id);
      if (target) target.quantity = quantity;
    }, offlineSession.clock_offset_ms)));
  }

  async function removeItem(itemId: string) {
    if (!currentOrder || !offlineSession || !canMutateCurrent) return;
    await run(async () => afterLocalWrite(await updateLocalOrder(currentOrder.id, (order) => {
      order.items = order.items.filter((item) => item.id !== itemId);
    }, offlineSession.clock_offset_ms)));
  }

  async function cancelOrder() {
    if (!currentOrder || !offlineSession || !canWriteLocal || loyaltyReserved) return;
    const reason = cancelReason.trim();
    if (!reason) return;
    await run(async () => {
      await cancelLocalOrder(currentOrder.id, reason, offlineSession.clock_offset_ms);
      await offline.reload();
      void offline.syncNow();
      setCurrentOrderId(orders.find((order) => order.id !== currentOrder.id && (order.status === "OPEN" || order.status === "SYNCED_OPEN"))?.id ?? "");
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

  async function openPayment() {
    if (!currentOrder || !canPay || currentOrder.items.length === 0) return;
    let priced = currentOrder;
    let ready = false;
    await run(async () => {
      if (!(offline.networkStatus === "ONLINE" && currentOrder.server_order_id && accessToken) && offlineSession) {
        priced = await updateLocalOrder(currentOrder.id, () => undefined, offlineSession.clock_offset_ms);
      }
      await afterLocalWrite(priced);
      ready = true;
    });
    if (!ready) return;
    setPaymentOrder(priced);
    setPaymentCustomerName(attachedCustomer ? posCustomerName(attachedCustomer) : null);
    setPaymentMode(null);
    setPaymentCashReceived(priceMinorToInput(priced.total_minor));
    setSplitCash("");
    setSplitCard(priceMinorToInput(priced.total_minor));
    setSplitOther("");
    setPaymentReference("");
    setCompletedPayment(null);
    const sameTerminalAttempt = terminalAttempt?.order_id === priced.server_order_id;
    setTerminalSelected(Boolean(sameTerminalAttempt));
    if (!sameTerminalAttempt) {
      setTerminalAttempt(null);
      pendingTerminal.current = null;
    }
    setCardConfirmed(false);
    setPaymentError("");
    pendingPayment.current = null;
  }

  function closePayment() {
    if (paymentBusy) return;
    setPaymentOrder(null);
    setPaymentCustomerName(null);
    setCompletedPayment(null);
    setPaymentError("");
    pendingPayment.current = null;
  }

  function choosePaymentMode(mode: PaymentMethod | "SPLIT") {
    setTerminalSelected(false);
    setPaymentMode(mode);
    setPaymentError("");
    setCardConfirmed(false);
    if (mode === "CASH" && paymentOrder) {
      setPaymentCashReceived(priceMinorToInput(paymentOrder.total_minor));
    }
  }

  async function applyDiscount(action: () => Promise<import("@/lib/api").SalesOrder>) {
    if (!currentOrder?.server_order_id || offline.networkStatus !== "ONLINE" || loyaltyReserved) return;
    await run(async () => {
      const priced = await action();
      await afterLocalWrite(await applyServerPricing(currentOrder.id, priced));
      setPromoCode(""); setCustomValue(""); setCustomReason("");
    });
  }

  async function searchCustomers() {
    if (!accessToken || !organizationId || offline.networkStatus !== "ONLINE" || !canReadCustomers) return;
    await run(async () => setCustomerResults(await api.listCustomers(organizationId, accessToken, { search: customerSearch.trim() || undefined, limit: 20 })));
  }

  async function attachCustomer(customer: Customer) {
    if (!accessToken || !organizationId || !currentOrder?.server_order_id || offline.networkStatus !== "ONLINE" || !canWriteCustomers) return;
    await run(async () => {
      const priced = await api.attachSalesOrderCustomer(currentOrder.server_order_id!, customer.id, organizationId, accessToken);
      await afterLocalWrite(await applyServerPricing(currentOrder.id, priced));
      setAttachedCustomer(customer);
      setCustomerLoyalty(canReadLoyalty ? await api.getCustomerLoyalty(customer.id, organizationId, accessToken) : null);
      setLoyaltyQuote(null); setLoyaltyPoints(""); setShowCustomers(false);
    });
  }

  async function createAndAttachCustomer() {
    if (!accessToken || !organizationId || !canWriteCustomers || !newCustomerPhone.trim()) return;
    await run(async () => {
      const [first_name, ...rest] = newCustomerName.trim().split(/\s+/).filter(Boolean);
      const customer = await api.createCustomer({ phone: newCustomerPhone.trim(), first_name: first_name || null, last_name: rest.join(" ") || null }, organizationId, accessToken);
      if (!currentOrder?.server_order_id) return;
      const priced = await api.attachSalesOrderCustomer(currentOrder.server_order_id, customer.id, organizationId, accessToken);
      await afterLocalWrite(await applyServerPricing(currentOrder.id, priced));
      setAttachedCustomer(customer);
      setCustomerLoyalty(canReadLoyalty ? await api.getCustomerLoyalty(customer.id, organizationId, accessToken) : null);
      setShowCustomers(false);
      setNewCustomerPhone(""); setNewCustomerName("");
    });
  }

  async function detachCustomer() {
    if (!accessToken || !organizationId || !currentOrder?.server_order_id || loyaltyReserved || !canWriteCustomers) return;
    await run(async () => {
      const priced = await api.attachSalesOrderCustomer(currentOrder.server_order_id!, null, organizationId, accessToken);
      await afterLocalWrite(await applyServerPricing(currentOrder.id, priced));
      setAttachedCustomer(null); setCustomerLoyalty(null); setLoyaltyQuote(null); setLoyaltyPoints("");
    });
  }

  async function quoteLoyalty() {
    if (!accessToken || !organizationId || !currentOrder?.server_order_id || !/^\d+$/.test(loyaltyPoints) || BigInt(loyaltyPoints) <= BigInt(0)) return;
    await run(async () => setLoyaltyQuote(await api.quoteSalesOrderLoyalty(currentOrder.server_order_id!, loyaltyPoints, organizationId, accessToken)));
  }

  async function redeemLoyalty() {
    if (!accessToken || !organizationId || !currentOrder?.server_order_id || !loyaltyQuote) return;
    const payload = `${currentOrder.server_order_id}:${loyaltyQuote.points}`;
    if (!pendingRedemption.current || pendingRedemption.current.payload !== payload) pendingRedemption.current = { id: crypto.randomUUID(), payload };
    await run(async () => {
      const priced = await api.redeemSalesOrderLoyalty(currentOrder.server_order_id!, loyaltyQuote.points, pendingRedemption.current!.id, organizationId, accessToken);
      await afterLocalWrite(await applyServerPricing(currentOrder.id, priced));
      setLoyaltyQuote(null); setLoyaltyPoints(""); pendingRedemption.current = null;
    });
  }

  async function releaseLoyalty() {
    if (!accessToken || !organizationId || !currentOrder?.server_order_id) return;
    await run(async () => {
      const priced = await api.releaseSalesOrderLoyalty(currentOrder.server_order_id!, organizationId, accessToken);
      await afterLocalWrite(await applyServerPricing(currentOrder.id, priced));
      setLoyaltyQuote(null); setLoyaltyPoints(""); pendingRedemption.current = null;
    });
  }

  async function applyManualPromotion(promotion: { id: string }) {
    if (!currentOrder) return;
    if (offline.networkStatus === "ONLINE" && currentOrder.server_order_id) {
      return applyDiscount(() => api.applyManualDiscount(currentOrder.server_order_id!, promotion.id, crypto.randomUUID(), currentOrder.organization_id, accessToken!));
    }
    if (!offlineSession) return;
    await run(async () => afterLocalWrite(await updateLocalOrder(currentOrder.id, (order) => {
      order.manual_promotion_ids = [...new Set([...(order.manual_promotion_ids ?? []), promotion.id])];
    }, offlineSession.clock_offset_ms)));
  }

  async function removeDiscount(discount: NonNullable<OfflineOrder["discounts"]>[number]) {
    if (!currentOrder) return;
    if (isLoyaltyDiscount(discount)) return releaseLoyalty();
    if (offline.networkStatus === "ONLINE" && currentOrder.server_order_id) return applyDiscount(() => api.removeSalesOrderDiscount(currentOrder.server_order_id!, discount.id, currentOrder.organization_id, accessToken!));
    if (!offlineSession || discount.source !== "MANUAL" || !discount.promotion_id) return;
    await run(async () => afterLocalWrite(await updateLocalOrder(currentOrder.id, (order) => {
      order.manual_promotion_ids = (order.manual_promotion_ids ?? []).filter((id) => id !== discount.promotion_id);
    }, offlineSession.clock_offset_ms)));
  }

  function chooseTerminalPayment() {
    setTerminalSelected(true);
    setPaymentMode(null);
    setPaymentError("");
    setCardConfirmed(false);
  }

  async function runTerminalPayment() {
    if (!accessToken || !organizationId || !paymentOrder || !paymentOrder.server_order_id || !terminalBinding || offline.networkStatus !== "ONLINE") return;
    const fingerprint = [paymentOrder.server_order_id, paymentOrder.total_minor, paymentOrder.currency_code, terminalBinding.id, terminalMethod].join(":");
    if (!pendingTerminal.current || pendingTerminal.current.fingerprint !== fingerprint) pendingTerminal.current = { id: crypto.randomUUID(), fingerprint };
    setPaymentBusy(true);
    setPaymentError("");
    let attempt = terminalAttempt;
    try {
      const action = attempt ? paymentAttemptAction(attempt.status) : "START";
      if (action === "RETRY") {
        pendingTerminal.current = { id: crypto.randomUUID(), fingerprint };
        attempt = null;
      }
      if (!attempt) {
        attempt = await api.createExternalPaymentAttempt({
          client_attempt_id: pendingTerminal.current.id,
          order_id: paymentOrder.server_order_id,
          register_id: selectedRegisterId,
          pos_device_id: offlineSession?.device_id ?? null,
          connection_id: terminalBinding.connection_id,
          provider_code: terminalBinding.provider_code,
          method: terminalMethod,
          amount_minor: paymentOrder.total_minor,
          currency_code: paymentOrder.currency_code,
        }, organizationId, accessToken);
        setTerminalAttempt(attempt);
      }
      const nextAction = paymentAttemptAction(attempt.status);
      if (nextAction === "START") attempt = await api.startExternalPaymentAttempt(attempt.id, organizationId, accessToken);
      else if (nextAction === "RECONCILE") attempt = await api.reconcileExternalPaymentAttempt(attempt.id, organizationId, accessToken);
      await applyTerminalAttempt(attempt);
    } catch {
      if (attempt?.id) {
        try {
          const recovered = await api.getExternalPaymentAttempt(attempt.id, organizationId, accessToken);
          await applyTerminalAttempt(recovered);
          if (recovered.status === "UNKNOWN" || recovered.status === "TERMINAL_PENDING") setPaymentError("Payment result is not final. Do not charge the customer again; check terminal status.");
        } catch {
          setPaymentError("Payment result could not be confirmed. Do not retry; recover this attempt before charging again.");
        }
      } else {
        setPaymentError("Payment request status is uncertain. Use the same attempt to recover status; do not charge again.");
      }
    } finally {
      setPaymentBusy(false);
    }
  }

  async function applyTerminalAttempt(attempt: ExternalPaymentAttempt) {
    setTerminalAttempt(attempt);
    if (attempt.status !== "APPROVED" || !paymentOrder) return;
    await markExternalPaymentApproved(paymentOrder.id, attempt);
    setCompletedPayment({ amount_minor: attempt.amount_minor, currency_code: attempt.currency_code, origin: "TERMINAL", lines: [{ method: "CARD", change_minor: "0" }] });
    await offline.reload();
    setCurrentOrderId(orders.find((order) => order.id !== paymentOrder.id && (order.status === "OPEN" || order.status === "SYNCED_OPEN"))?.id ?? "");
    pendingTerminal.current = null;
  }

  function updateSplitCash(value: string) {
    setSplitCash(value);
    setPaymentCashReceived(value);
    const cashMinor = paymentInputMinor(value);
    if (paymentOrder && cashMinor !== null && !splitOther.trim()) {
      const remaining = BigInt(paymentOrder.total_minor) - BigInt(cashMinor);
      if (remaining >= BigInt(0)) setSplitCard(priceMinorToInput(String(remaining)));
    }
  }

  async function completePayment() {
    if (!offlineSession || !canWriteLocal || !paymentOrder || paymentDraft.error || (needsSettlementConfirmation && !cardConfirmed)) return;
    const payload = JSON.stringify(paymentDraft.lines);
    if (!pendingPayment.current || pendingPayment.current.payload !== payload) {
      pendingPayment.current = { id: crypto.randomUUID(), payload };
    }
    setPaymentBusy(true);
    setPaymentError("");
    try {
      const lines = paymentDraft.lines.map((line) => ({
        ...line,
        ...((line.method === "CARD" || line.method === "OTHER") ? { external_settlement_confirmed: true } : {}),
      }));
      await payLocalOrder(
        paymentOrder.id,
        pendingPayment.current.id,
        lines,
        offlineSession.clock_offset_ms,
      );
      setCompletedPayment({
        amount_minor: paymentOrder.total_minor,
        currency_code: paymentOrder.currency_code,
        origin: "LOCAL",
        lines: lines.map((line) => ({
          method: line.method,
          change_minor: line.method === "CASH" ? String(paymentDraft.changeMinor) : "0",
        })),
      });
      await offline.reload();
      void offline.syncNow();
      setCurrentOrderId(orders.find((order) => order.id !== paymentOrder.id && (order.status === "OPEN" || order.status === "SYNCED_OPEN"))?.id ?? "");
      pendingPayment.current = null;
    } catch (caught) {
      setPaymentError(messageOf(caught));
    } finally {
      setPaymentBusy(false);
    }
  }

  async function startNewOrderAfterPayment() {
    closePayment();
    await createOrder();
  }

  function editItemConfiguration(item: OfflineOrderItem) {
    if (!canCreate || !canWriteLocal) return;
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
          <p>Choose a register and warehouse for {currentLocation?.name ?? "this location"}.</p>
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
          <label className="modal-field">
            <span>Starting cash</span>
            <input inputMode="decimal" value={startingCash} onChange={(event) => setStartingCash(event.target.value)} />
          </label>
          {warehouses.length === 0 && <p className="pos-hint">No accessible active warehouse is available for this location.</p>}
          <button className="primary-button pos-open-shift" disabled={busy || !canManageShift || !selectedRegisterId || !selectedWarehouseId || !parseMenuPriceToMinor(startingCash)} type="button" onClick={openShift}>
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
          <span className="pos-eyebrow">{currentLocation?.name ?? offlineSession?.shell.location_name} · {selectedRegister?.name ?? offlineSession?.shell.register_name}</span>
          <strong><Clock3 aria-hidden="true" /> Shift opened {formatTime(shift.opened_at)}</strong>
        </div>
        <div className="pos-header-actions">
          {canReadRefunds && <Link className="secondary-button" href="/app/pos/refunds">Order history</Link>}
          <button className="secondary-button" type="button" onClick={() => setShowOrders((current) => !current)}>Orders ({orders.length})</button>
          {offlineSession && canManageDevice && <button className="secondary-button" disabled={busy || !accessToken || hasOpenOrders || offline.unresolvedCount > 0 || offline.networkStatus !== "ONLINE"} type="button" onClick={disableOffline}>Disable offline</button>}
          {accessToken && organizationId && (
            <CashDrawerControls
              accessToken={accessToken}
              organizationId={organizationId}
              shift={shift}
              drawer={drawer}
              currency={currency}
              permissions={permissions}
              pendingOperations={offline.unresolvedCount}
              hasOpenOrders={hasOpenOrders}
              online={offline.networkStatus === "ONLINE"}
              busy={busy}
              onCloseStarted={markCashCloseStarted}
              onDrawer={setDrawer}
              onClosed={finishCashClose}
            />
          )}
        </div>
      </header>
      <div className="pos-status-row">
        <ConnectionStatus status={offline.networkStatus} />
        <SyncStatus state={offline.syncState} pending={offline.unresolvedCount} pendingTotal={offline.pendingTotal} currency={currency} disabled={!offline.isWriter} onSync={() => { void offline.syncNow(); }} />
        <OfflineReady readiness={offline.storage} onPrepare={() => { void offline.requestPersistence(); }} />
      </div>
      {!offlineSession && <p className="pos-notice">Offline sales are not ready on this terminal.<button disabled={!accessToken || busy} type="button" onClick={enableOffline}>Enable offline POS</button></p>}
      {offlineSession && !sessionActive && <p className="pos-notice">Offline session expired. Existing orders remain safe and can sync.{offline.unresolvedCount === 0 && <button disabled={!accessToken || busy || offline.networkStatus !== "ONLINE"} type="button" onClick={enableOffline}>Start new offline session</button>}</p>}
      {!offline.isWriter && <p className="pos-notice">POS is already open in another window. This tab is read-only.</p>}
      {offline.updatePending && <p className="pos-notice">Beanly update available.{offline.unresolvedCount > 0 ? " Update waits until pending sales are synchronized or reviewed." : ""}<button disabled={offline.unresolvedCount > 0} type="button" onClick={offline.applyUpdate}>Update now</button></p>}
      {error && <p className="pos-global-error" role="alert">{error}</p>}

      <div className="pos-grid">
        <aside className={showOrders ? "pos-orders-drawer is-open" : "pos-orders-drawer"}>
          <div className="pos-panel-title">
            <button className="icon-button" type="button" aria-label="Hide orders" onClick={() => setShowOrders(false)}><ChevronLeft /></button>
            <h2>Open orders</h2>
          </div>
          <button className="primary-button" disabled={busy || !canCreate || !canWriteLocal} type="button" onClick={() => createOrder()}>+ New order</button>
          <div className="pos-order-list">
            {orders.map((order) => (
              <button className={order.id === selectedOrder?.id ? "is-active" : ""} key={order.id} type="button" onClick={() => { setCurrentOrderId(order.id); setShowOrders(false); }}>
                <span><strong>{displayOrderNumber(order)}</strong>{prettyOrderType(order.order_type)}<small className="pos-order-state">{prettyOrderStatus(order.status)}</small></span>
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
              <h2>{selectedOrder?.status === "CONFLICT" ? "Paid order needs manager review" : selectedOrder?.status === "PAID_PENDING_SYNC" ? "Payment pending sync" : "Create or select an order"}</h2>
              <p>{selectedOrder?.status === "CONFLICT" ? `Payment has not been posted: ${selectedOrder.sync_error ?? "server conflict"}.` : selectedOrder?.status === "PAID_PENDING_SYNC" ? "This paid order is immutable. Fiscal receipt: Pending sync." : "Every change is committed locally first, then synchronized."}</p>
              {!selectedOrder && <button className="primary-button" disabled={busy || !canCreate || !canWriteLocal} type="button" onClick={() => createOrder()}>Create order</button>}
            </div>
          ) : (
            <div className="pos-product-grid">
              {products.map((product) => {
                const activeVariants = product.variants.filter((variant) => variant.status === "ACTIVE");
                const from = activeVariants.reduce<string | null>((lowest, variant) => lowest === null || BigInt(variant.effective_price_minor) < BigInt(lowest) ? variant.effective_price_minor : lowest, null);
                return (
                  <button disabled={busy || !canMutateCurrent || menuCatalogId !== currentOrder.catalog_snapshot_id || !activeVariants.length || product.is_available === false || product.is_visible === false} key={product.id} type="button" onClick={() => chooseProduct(product)}>
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
                <div><span>Current order</span><h2>{displayOrderNumber(currentOrder)}</h2></div>
                <select aria-label="Order type" disabled={busy || !canMutateCurrent} value={currentOrder.order_type} onChange={(event) => run(async () => { if (!offlineSession) return; await afterLocalWrite(await updateLocalOrder(currentOrder.id, (order) => { order.order_type = event.target.value as SalesOrderType; }, offlineSession.clock_offset_ms)); })}>
                  <option value="DINE_IN">Dine-in</option><option value="TAKEAWAY">Takeaway</option><option value="DELIVERY">Delivery</option>
                </select>
              </div>
              <div className="pos-receipt-items">
                {currentOrder.items.map((item) => (
                  <article key={item.id}>
                    <div className="pos-line-main">
                      <div><strong>{item.product_name}</strong><span>{item.variant_name}</span></div>
                      <b className={BigInt(item.discount_amount_minor ?? "0") > BigInt(0) ? "pos-line-discounted" : ""}>{BigInt(item.discount_amount_minor ?? "0") > BigInt(0) && <del>{formatMenuPriceMinor(item.line_total_minor, currentOrder.currency_code)}</del>}{formatMenuPriceMinor(item.net_line_total_minor ?? item.line_total_minor, currentOrder.currency_code)}</b>
                    </div>
                    {item.modifiers.length > 0 && <p>{item.modifiers.map((modifier) => modifier.modifier_option_name).join(" · ")}</p>}
                    {item.note && <p>{item.note}</p>}
                    <div className="pos-line-actions">
                      <span className="pos-quantity"><button aria-label={`Decrease ${item.product_name}`} disabled={busy || !canMutateCurrent || item.quantity <= 1} type="button" onClick={() => updateQuantity(item, item.quantity - 1)}><Minus /></button><b>{item.quantity}</b><button aria-label={`Increase ${item.product_name}`} disabled={busy || !canMutateCurrent} type="button" onClick={() => updateQuantity(item, item.quantity + 1)}><Plus /></button></span>
                      <button disabled={busy || !canMutateCurrent} type="button" onClick={() => editItemConfiguration(item)}>Customize</button>
                      <button className="danger-link" aria-label={`Remove ${item.product_name}`} disabled={busy || !canMutateCurrent} type="button" onClick={() => removeItem(item.id)}><Trash2 /></button>
                    </div>
                  </article>
                ))}
                {currentOrder.items.length === 0 && <div className="pos-receipt-empty"><ShoppingBag aria-hidden="true" /><p>Add a product to start this order.</p></div>}
              </div>
              <button className="pos-customer-button" disabled={busy || !canReadCustomers || (!attachedCustomer && !canWriteCustomers) || offline.networkStatus !== "ONLINE" || !currentOrder.server_order_id} type="button" onClick={() => { setCustomerSearch(""); setCustomerResults([]); setShowCustomers(true); }}><UserRound /><span>{attachedCustomer ? <><strong>{posCustomerName(attachedCustomer)}</strong><small>{attachedCustomer.tier?.name ?? "Member"}{customerLoyalty ? ` · ${formatPoints(customerLoyalty.available_points)} points` : ""}</small></> : <><strong>Add customer</strong><small>{offline.networkStatus === "ONLINE" ? "Search by phone or name" : "Online only"}</small></>}</span></button>
              {attachedCustomer && (currentOrder.discounts ?? []).some((discount) => discount.audience_kind) && <p className="pos-customer-promotion">✓ Customer offer applied</p>}
              {(currentOrder.discounts ?? []).length > 0 && <div className="pos-discount-lines">{currentOrder.discounts.map((discount) => <div key={discount.id}><span>{discount.source === "AUTOMATIC" && "⚡ "}{discount.promotion_name}{discount.audience_kind && <small>{audienceLabel(discount.audience_kind)}</small>}</span><strong>−{formatMenuPriceMinor(discount.discount_total_minor, currentOrder.currency_code)}</strong>{discount.source !== "AUTOMATIC" && (isLoyaltyDiscount(discount) ? canRedeemLoyalty : canApplyDiscount) && <button aria-label={`Remove ${discount.promotion_name}`} disabled={busy || (offline.networkStatus !== "ONLINE" && discount.source !== "MANUAL")} type="button" onClick={() => void removeDiscount(discount)}><X /></button>}</div>)}</div>}
              <button className="pos-discounts-button" disabled={!canApplyDiscount || !canWriteLocal || loyaltyReserved} type="button" onClick={() => setShowDiscounts(true)}><Tags />Discounts{BigInt(currentOrder.discount_total_minor ?? "0") > BigInt(0) && <span>Save {formatMenuPriceMinor(currentOrder.discount_total_minor, currentOrder.currency_code)}</span>}</button>
              {BigInt(currentOrder.discount_total_minor ?? "0") > BigInt(0) && <div className="pos-receipt-subtotal"><span>Subtotal</span><strong>{formatMenuPriceMinor(currentOrder.subtotal_minor, currentOrder.currency_code)}</strong></div>}
              <div className="pos-receipt-total"><span>Total</span><strong>{formatMenuPriceMinor(currentOrder.total_minor, currentOrder.currency_code)}</strong></div>
              <button className="primary-button pos-pay-button" disabled={busy || !canPay || !canWriteLocal || currentOrder.items.length === 0} type="button" onClick={openPayment}>Pay · {formatMenuPriceMinor(currentOrder.total_minor, currentOrder.currency_code)}</button>
              {canCancel && <button className="pos-cancel-order" disabled={busy || !canWriteLocal || loyaltyReserved} type="button" onClick={openCancelDialog}>Cancel order</button>}
            </>
          ) : (
            <div className="pos-receipt-empty"><ShoppingBag aria-hidden="true" /><h2>No order selected</h2></div>
          )}
        </aside>
      </div>

      {showDiscounts && currentOrder && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card pos-discount-modal" role="dialog" aria-modal="true" aria-labelledby="pos-discount-title">
            <button className="modal-close" type="button" aria-label="Close discounts" onClick={() => setShowDiscounts(false)}><X /></button>
            <span className="pos-eyebrow">Current order</span><h2 id="pos-discount-title">Discounts</h2>
            <>
              <section className="pos-discount-group"><h3>Automatic</h3>{(currentOrder.discounts ?? []).filter((discount) => discount.source === "AUTOMATIC").map((discount) => <p key={discount.id}>✓ {discount.promotion_name} <strong>−{formatMenuPriceMinor(discount.discount_total_minor, currentOrder.currency_code)}</strong></p>)}{!(currentOrder.discounts ?? []).some((discount) => discount.source === "AUTOMATIC") && <small>No automatic promotion matched.</small>}</section>
              <section className="pos-discount-group"><h3>Manual</h3>{manualPromotionChoices.filter((promotion) => !promotion.requiresOverride || (offline.networkStatus === "ONLINE" && canOverrideDiscount)).map((promotion) => <button disabled={busy} key={promotion.id} type="button" onClick={() => void applyManualPromotion(promotion)}><span>{promotion.name}</span><small>{promotion.kind === "PERCENT" ? `${promotion.percent}%` : promotion.kind.replaceAll("_", " ")}</small></button>)}{manualPromotionChoices.length === 0 && <small>No manual presets available.</small>}</section>
              <section className="pos-discount-group"><h3>Promo code</h3>{offline.networkStatus !== "ONLINE" || !currentOrder.server_order_id ? <small>Promo codes require an online, synced order.</small> : <div className="pos-discount-code"><input maxLength={80} placeholder="Enter code" value={promoCode} onChange={(event) => setPromoCode(event.target.value.toUpperCase())} /><button className="secondary-button" disabled={busy || !promoCode.trim()} type="button" onClick={() => void applyDiscount(() => api.applyPromoCode(currentOrder.server_order_id!, promoCode, crypto.randomUUID(), currentOrder.organization_id, accessToken!))}>Apply</button></div>}</section>
              {canOverrideDiscount && <section className="pos-discount-group"><h3>Manager · Custom discount</h3>{offline.networkStatus !== "ONLINE" || !currentOrder.server_order_id ? <small>Custom discounts require an online, synced order.</small> : <div className="pos-custom-discount"><select value={customType} onChange={(event) => setCustomType(event.target.value as typeof customType)}><option value="PERCENT">Percent</option><option value="FIXED_AMOUNT">Fixed amount</option></select><input min="0" step={customType === "PERCENT" ? "0.0001" : "0.01"} type="number" placeholder={customType === "PERCENT" ? "15" : "500"} value={customValue} onChange={(event) => setCustomValue(event.target.value)} /><input maxLength={1000} placeholder="Reason (required)" value={customReason} onChange={(event) => setCustomReason(event.target.value)} /><button className="secondary-button" disabled={busy || !customValue || !customReason.trim()} type="button" onClick={() => void applyDiscount(() => api.applyCustomDiscount(currentOrder.server_order_id!, { client_discount_id: crypto.randomUUID(), type: customType, ...(customType === "PERCENT" ? { percent: customValue } : { amount_minor: parseMenuPriceToMinor(customValue)! }), reason: customReason.trim() }, currentOrder.organization_id, accessToken!))}>Apply custom</button></div>}</section>}
            </>
            {error && <p className="form-message error" role="alert">{error}</p>}
          </div>
        </div>
      )}

      {showCustomers && currentOrder && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card pos-customer-modal" role="dialog" aria-modal="true" aria-labelledby="pos-customer-title">
            <button className="modal-close" type="button" aria-label="Close customers" onClick={() => setShowCustomers(false)}><X /></button>
            <span className="pos-eyebrow">Current order</span><h2 id="pos-customer-title">Customer &amp; loyalty</h2>
            {attachedCustomer && <section className="pos-customer-summary"><span className="customer-avatar">{posCustomerName(attachedCustomer).charAt(0)}</span><div><strong>{posCustomerName(attachedCustomer)}</strong><small>{attachedCustomer.phone}{attachedCustomer.tier ? ` · ${attachedCustomer.tier.name}` : ""}</small></div>{canWriteCustomers && <button className="text-button" disabled={busy || loyaltyReserved} type="button" onClick={() => void detachCustomer()}>Detach</button>}</section>}
            {attachedCustomer && customerLoyalty && <section className="pos-loyalty"><div><span>Available points</span><strong>{formatPoints(customerLoyalty.available_points)}</strong><small>{formatMenuPriceMinor(customerLoyalty.point_value_minor, currentOrder.currency_code)} each · earned after payment</small></div>{loyaltyReserved ? <div className="pos-loyalty-reserved"><span>Points reserved for this order</span><button className="menu-secondary-button" disabled={busy} type="button" onClick={() => void releaseLoyalty()}>Release points</button></div> : canRedeemLoyalty && <><div className="pos-loyalty-quote"><input aria-label="Points to redeem" inputMode="numeric" placeholder="Points to redeem" value={loyaltyPoints} onChange={(event) => { setLoyaltyPoints(event.target.value); setLoyaltyQuote(null); }} /><button className="menu-secondary-button" disabled={busy || !/^\d+$/.test(loyaltyPoints) || BigInt(loyaltyPoints || "0") <= BigInt(0)} type="button" onClick={() => void quoteLoyalty()}>Quote</button></div>{loyaltyQuote && <div className="pos-loyalty-preview"><span>{formatPoints(loyaltyQuote.points)} points</span><strong>−{formatMenuPriceMinor(loyaltyQuote.discount_minor, currentOrder.currency_code)}</strong><button className="menu-primary-button" disabled={busy} type="button" onClick={() => void redeemLoyalty()}>Apply points</button></div>}</>}</section>}
            {!loyaltyReserved && canWriteCustomers && <section className="pos-customer-search"><h3>{attachedCustomer ? "Change customer" : "Find customer"}</h3><form onSubmit={(event) => { event.preventDefault(); void searchCustomers(); }}><input autoFocus={!attachedCustomer} aria-label="Customer phone or name" placeholder="Phone or name" value={customerSearch} onChange={(event) => setCustomerSearch(event.target.value)} /><button className="menu-secondary-button" disabled={busy} type="submit"><Search />Search</button></form><div>{customerResults.map((customer) => <button key={customer.id} type="button" onClick={() => void attachCustomer(customer)}><span><strong>{posCustomerName(customer)}</strong><small>{customer.phone}</small></span><span>{customer.tier?.name ?? ""}{customer.loyalty_points_balance !== "0" ? ` · ${formatPoints(customer.loyalty_points_balance)} points` : ""}</span></button>)}</div></section>}
            {!attachedCustomer && canWriteCustomers && <section className="pos-customer-create"><h3>Quick create</h3><div><input aria-label="New customer phone" required type="tel" placeholder="Phone" value={newCustomerPhone} onChange={(event) => setNewCustomerPhone(event.target.value)} /><input aria-label="New customer name" placeholder="Name (optional)" value={newCustomerName} onChange={(event) => setNewCustomerName(event.target.value)} /><button className="menu-secondary-button" disabled={busy || !newCustomerPhone.trim()} type="button" onClick={() => void createAndAttachCustomer()}><Plus />Create &amp; attach</button></div></section>}
          </div>
        </div>
      )}

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
            <label className="modal-field"><span>Item note (optional)</span><input maxLength={1000} placeholder="No sugar" value={configurationNote} onChange={(event) => setConfigurationNote(event.target.value)} /></label>
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
      {paymentOrder && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card pos-payment-modal" role="dialog" aria-busy={paymentBusy} aria-modal="true" aria-labelledby="pos-payment-title" onKeyDown={(event) => { if (event.key === "Escape") closePayment(); }}>
            <button className="modal-close" disabled={paymentBusy} type="button" aria-label="Close payment" onClick={closePayment}><X /></button>
            {completedPayment ? (
              <div className="pos-payment-success" role="status">
                <span className="pos-payment-check" aria-hidden="true">✓</span>
                <span className="pos-eyebrow">Payment successful</span>
                <h2 id="pos-payment-title">{displayOrderNumber(paymentOrder)}</h2>
                <strong>{formatMenuPriceMinor(completedPayment.amount_minor, completedPayment.currency_code)}</strong>
                <p>{completedPayment.lines.length > 0 ? completedPayment.lines.map((line) => paymentMethodNames.get(line.method) ?? line.method).join(" + ") : "Complimentary"}</p>
                {completedPayment.lines.some((line) => BigInt(line.change_minor) > BigInt(0)) && (
                  <p>Change · {formatMenuPriceMinor(String(completedPayment.lines.reduce((sum, line) => sum + BigInt(line.change_minor), BigInt(0))), completedPayment.currency_code)}</p>
                )}
                <p>{completedPayment.origin === "TERMINAL" ? "Provider approved · Fiscal receipt processing" : "Recorded locally · Fiscal receipt pending sync"}</p>
                {paymentCustomerName && <p>{paymentCustomerName} · Loyalty points post after payment sync</p>}
                <div className="modal-actions">
                  {completedPayment.origin === "TERMINAL" && <Link className="secondary-button" href="/app/fiscal">Fiscal receipt</Link>}
                  <button className="secondary-button" type="button" onClick={closePayment}>Done</button>
                  {canCreate && <button className="primary-button" disabled={busy} type="button" onClick={startNewOrderAfterPayment}>+ New order</button>}
                </div>
              </div>
            ) : (
              <>
                <span className="pos-eyebrow">{displayOrderNumber(paymentOrder)}</span>
                <h2 id="pos-payment-title">Payment</h2>
                <div className="pos-payment-total"><span>Total</span><strong>{formatMenuPriceMinor(paymentOrder.total_minor, paymentOrder.currency_code)}</strong></div>
                {BigInt(paymentOrder.total_minor) === BigInt(0) ? (
                  <p className="pos-payment-free">No payment method is needed for this complimentary order.</p>
                ) : (
                  <>
                    <div className="pos-payment-methods" role="group" aria-label="Payment method">
                      {terminalBinding && <button autoFocus className={terminalSelected ? "is-active pos-terminal-method" : "pos-terminal-method"} disabled={paymentBusy} type="button" onClick={chooseTerminalPayment}><CreditCard aria-hidden="true" /><span><strong>{terminalBinding.provider_code.includes("kaspi") ? "Kaspi POS" : terminalBinding.provider_code}</strong><small>Card / QR</small></span></button>}
                      {paymentMethods.map((method) => (
                        <button autoFocus={!terminalBinding && method.code === "CASH"} className={paymentMode === method.code ? "is-active" : ""} disabled={paymentBusy} key={method.code} type="button" onClick={() => choosePaymentMode(method.code)}>{method.name}</button>
                      ))}
                      <button className={paymentMode === "SPLIT" ? "is-active" : ""} disabled={paymentBusy} type="button" onClick={() => choosePaymentMode("SPLIT")}>Split payment</button>
                    </div>
                    {paymentMode === "CASH" && (
                      <div className="pos-payment-fields">
                        <label className="modal-field"><span>Cash received</span><input autoFocus inputMode="decimal" placeholder="0" value={paymentCashReceived} onChange={(event) => setPaymentCashReceived(event.target.value)} /></label>
                        <PaymentBalance label="Change" amount={paymentDraft.changeMinor} currency={paymentOrder.currency_code} />
                      </div>
                    )}
                    {paymentMode === "CARD" && <p className="pos-payment-note">Record this only after the external card terminal approves the payment.</p>}
                    {paymentMode === "OTHER" && (
                      <div className="pos-payment-fields"><label className="modal-field"><span>Reference (optional)</span><input autoFocus maxLength={200} placeholder="Provider or note" value={paymentReference} onChange={(event) => setPaymentReference(event.target.value)} /></label></div>
                    )}
                    {paymentMode === "SPLIT" && (
                      <div className="pos-split-fields">
                        <label className="modal-field"><span>Cash</span><input autoFocus inputMode="decimal" placeholder="0" value={splitCash} onChange={(event) => updateSplitCash(event.target.value)} /></label>
                        <label className="modal-field"><span>Cash received</span><input inputMode="decimal" placeholder="0" value={paymentCashReceived} onChange={(event) => setPaymentCashReceived(event.target.value)} /></label>
                        <label className="modal-field"><span>Card</span><input inputMode="decimal" placeholder="0" value={splitCard} onChange={(event) => setSplitCard(event.target.value)} /></label>
                        <label className="modal-field"><span>Other</span><input inputMode="decimal" placeholder="0" value={splitOther} onChange={(event) => setSplitOther(event.target.value)} /></label>
                        {BigInt(paymentDraft.changeMinor) > BigInt(0) && <PaymentBalance label="Cash change" amount={paymentDraft.changeMinor} currency={paymentOrder.currency_code} />}
                        <PaymentBalance label={paymentDraft.remainingMinor < BigInt(0) ? "Over" : "Remaining"} amount={paymentDraft.remainingMinor < BigInt(0) ? -paymentDraft.remainingMinor : paymentDraft.remainingMinor} currency={paymentOrder.currency_code} />
                      </div>
                    )}
                    {terminalSelected && (
                      <><div className="pos-terminal-method-toggle" role="group" aria-label="Terminal payment type"><button className={terminalMethod === "CARD" ? "is-active" : ""} disabled={Boolean(terminalAttempt) || paymentBusy} type="button" onClick={() => setTerminalMethod("CARD")}>Card</button><button className={terminalMethod === "QR" ? "is-active" : ""} disabled={Boolean(terminalAttempt) || paymentBusy} type="button" onClick={() => setTerminalMethod("QR")}>QR</button></div><div className={`pos-terminal-state${terminalAttempt?.status === "UNKNOWN" ? " is-unknown" : ""}`} role="status">
                        {terminalAttempt?.status === "UNKNOWN" ? <ShieldAlert aria-hidden="true" /> : <CreditCard aria-hidden="true" />}
                        <div>
                          <strong>{terminalAttempt ? terminalStatusCopy(terminalAttempt.status) : terminalOrderReady ? `Send ${formatMenuPriceMinor(paymentOrder.total_minor, paymentOrder.currency_code)} to terminal` : "Terminal payment unavailable"}</strong>
                          <p>{terminalAttempt?.status === "UNKNOWN" ? "Do not charge the customer again. Beanly must reconcile this attempt first." : terminalAttempt?.status === "TERMINAL_PENDING" ? "Keep this payment open while the customer completes Card / QR on Smart POS." : terminalAttempt?.status === "DECLINED" || terminalAttempt?.status === "CANCELLED" ? "This attempt ended definitively. A new attempt is safe." : !terminalOrderReady ? offline.networkStatus !== "ONLINE" ? "Connection is required. Offline terminal charging is not supported by this provider." : "Wait until this order is fully synced before sending the exact amount." : "The amount and order are verified by Beanly before the terminal starts."}</p>
                          {terminalAttempt?.failure_code && <small>Reason: {terminalAttempt.failure_code}</small>}
                        </div>
                      </div></>
                    )}
                  </>
                )}
                {needsSettlementConfirmation && !paymentDraft.error && (
                  <label className="pos-payment-confirm"><input type="checkbox" checked={cardConfirmed} onChange={(event) => setCardConfirmed(event.target.checked)} /><span>I confirm the card or external settlement was approved outside Beanly. No card credentials are stored.</span></label>
                )}
                {paymentMode && paymentDraft.error && <p className="form-message error" role="alert">{paymentDraft.error}</p>}
                {paymentError && <p className="form-message error" role="alert">{paymentError}</p>}
                <div className="modal-actions"><button className="secondary-button" disabled={paymentBusy} type="button" onClick={closePayment}>Cancel</button>{terminalSelected ? <button className="primary-button" disabled={paymentBusy || !terminalOrderReady || terminalAttempt?.status === "APPROVED"} type="button" onClick={() => void runTerminalPayment()}>{paymentBusy ? "Checking…" : terminalAction === "RECONCILE" ? "Check status" : terminalAction === "RETRY" ? "Try again" : "Send to terminal"}</button> : <button className="primary-button" disabled={paymentBusy || !canWriteLocal || Boolean(paymentDraft.error) || (needsSettlementConfirmation && !cardConfirmed)} type="button" onClick={completePayment}>{paymentBusy ? "Recording…" : "Record payment"}</button>}</div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function PaymentBalance({ label, amount, currency }: { label: string; amount: bigint; currency: string }) {
  return <div className="pos-payment-balance"><span>{label}</span><strong>{formatMenuPriceMinor(String(amount), currency)}</strong></div>;
}

function configurationPrice(variant: ProductVariant, selectedOptionIds: string[]) {
  return String((variant.modifier_groups ?? []).flatMap((group) => group.options)
    .filter((option) => selectedOptionIds.includes(option.id))
    .reduce((total, option) => total + BigInt(option.effective_price_delta_minor), BigInt(variant.effective_price_minor)));
}

function configurationIsValid(variant: ProductVariant, selectedOptionIds: string[]) {
  const selected = new Set(selectedOptionIds);
  const available = new Set((variant.modifier_groups ?? []).filter((group) => group.is_active)
    .flatMap((group) => group.options.filter((option) => option.is_available).map((option) => option.id)));
  return selectedOptionIds.every((id) => available.has(id)) && (variant.modifier_groups ?? []).filter((group) => group.is_active).every((group) => {
    const count = group.options.filter((option) => option.is_available && selected.has(option.id)).length;
    return count >= group.min_selections && count <= group.max_selections;
  });
}

function displayOrderNumber(order: OfflineOrder) {
  return order.server_order_id ? `Order #${order.number}` : order.number;
}

function prettyOrderStatus(status: OfflineOrder["status"]) {
  if (status === "PAID_PENDING_SYNC") return "Paid · pending sync";
  if (status === "CANCELLED_PENDING_SYNC") return "Cancelled · pending sync";
  if (status === "CONFLICT") return "Needs review";
  if (status === "SYNCED_OPEN") return "Synced";
  return "Pending sync";
}

function shiftFromSession(session: OfflineSession): RegisterShift {
  return {
    id: session.shift_id,
    organization_id: session.organization_id,
    location_id: session.location_id,
    register_id: session.register_id,
    warehouse_id: session.warehouse_id,
    drawer_session_id: null,
    status: "OPEN",
    opened_by_user_id: session.actor_user_id,
    closed_by_user_id: null,
    opened_at: session.started_at,
    closed_at: null,
    created_at: session.started_at,
    updated_at: session.started_at,
  };
}

function prettyOrderType(value: SalesOrderType) {
  if (value === "DINE_IN") return "Dine-in";
  if (value === "DELIVERY") return "Delivery";
  return "Takeaway";
}

function paymentInputMinor(value: string) {
  return value.trim() ? parseMenuPriceToMinor(value) : "0";
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function posCustomerName(customer: Customer) {
  return [customer.first_name, customer.last_name].filter(Boolean).join(" ") || customer.phone;
}

function formatPoints(value: string) {
  return new Intl.NumberFormat("en").format(BigInt(value));
}

function isLoyaltyDiscount(discount: { promotion_name: string; reason: string | null }) {
  return discount.promotion_name === "Loyalty redemption" && discount.reason?.startsWith("LOYALTY_REDEMPTION");
}

function audienceLabel(kind: "CUSTOMER" | "TIER" | "BIRTHDAY") {
  if (kind === "BIRTHDAY") return " · Birthday offer";
  if (kind === "TIER") return " · Tier offer";
  return " · Customer offer";
}

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
