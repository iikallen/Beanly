"use client";

import { Check, CircleAlert, Link2, Pencil, RefreshCcw, Search, ShieldCheck, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useIntegrationPermissions } from "@/hooks/use-integration-permissions";
import {
  ApiError,
  api,
  type FiscalEnforcement,
  type FiscalEnforcementMode,
  type FiscalGoLiveReadiness,
  type FiscalReadiness,
  type FiscalRoute,
  type FiscalTaxProfile,
  type FiscalVariantProfile,
  type IntegrationConnection,
  type IntegrationProvider,
  type NktProduct,
  type PosRegister,
  type TerminalBinding,
} from "@/lib/api";
import { localDateInput } from "@/lib/dashboard";
import { trapDialogFocus } from "@/lib/dialog";

type TaxDraft = Pick<FiscalTaxProfile, "country_code" | "tax_regime_code" | "vat_registered" | "effective_from"> & { default_vat_rate: string };
type VariantDraft = Pick<FiscalVariantProfile, "fiscal_name" | "nkt_code" | "nkt_code_type" | "fiscal_unit_code" | "vat_rate_override" | "requires_marking">;

const emptyVariant: VariantDraft = { fiscal_name: "", nkt_code: null, nkt_code_type: null, fiscal_unit_code: "pcs", vat_rate_override: null, requires_marking: false };

export default function FiscalSettingsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const permissions = useIntegrationPermissions();
  const searchParams = useSearchParams();
  const linkedVariantId = searchParams.get("variant_id") ?? "";
  const linkedVariantName = searchParams.get("variant_name") ?? "Selected variant";
  const [profile, setProfile] = useState<FiscalTaxProfile | null>(null);
  const [readiness, setReadiness] = useState<FiscalReadiness | null>(null);
  const [loadedOrganizationId, setLoadedOrganizationId] = useState("");
  const [tax, setTax] = useState<TaxDraft>(() => newTaxDraft("KZ"));
  const [variantId, setVariantId] = useState("");
  const [variantName, setVariantName] = useState("");
  const [variant, setVariant] = useState<VariantDraft>(emptyVariant);
  const [variantProfile, setVariantProfile] = useState<FiscalVariantProfile | null>(null);
  const [nktMode, setNktMode] = useState<"CACHE" | "NTIN" | "GTIN">("CACHE");
  const [nktQuery, setNktQuery] = useState("");
  const [nktResults, setNktResults] = useState<NktProduct[]>([]);
  const [selectedNtin, setSelectedNtin] = useState("");
  const [nktBusy, setNktBusy] = useState(false);
  const [enforcement, setEnforcement] = useState<FiscalEnforcement | null>(null);
  const [goLive, setGoLive] = useState<FiscalGoLiveReadiness | null>(null);
  const [routes, setRoutes] = useState<FiscalRoute[]>([]);
  const [registers, setRegisters] = useState<PosRegister[]>([]);
  const [connections, setConnections] = useState<IntegrationConnection[]>([]);
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [terminalBindings, setTerminalBindings] = useState<TerminalBinding[]>([]);
  const [routeRegisterId, setRouteRegisterId] = useState("");
  const [routeConnectionId, setRouteConnectionId] = useState("");
  const [routeSourceMode, setRouteSourceMode] = useState<FiscalRoute["source_mode"]>("EXTERNAL_KKM");
  const [terminalConnectionId, setTerminalConnectionId] = useState("");
  const [externalTerminalId, setExternalTerminalId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const requestId = useRef(0);
  const activeOrganizationId = useRef(currentOrganization?.id ?? "");
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => { activeOrganizationId.current = currentOrganization?.id ?? ""; }, [currentOrganization?.id]);

  const load = useCallback(async () => {
    const activeRequestId = ++requestId.current;
    if (!accessToken || !currentOrganization || !currentLocation || permissions.loading || !permissions.canReadFiscal) {
      setProfile(null);
      setReadiness(null);
      setLoadedOrganizationId("");
      setLoading(false);
      return;
    }
    setLoading(true);
    setSaving(false);
    setVariantId("");
    setError("");
    setLoadedOrganizationId("");
    setProfile(null);
    setReadiness(null);
    try {
      const [nextProfile, nextReadiness, nextEnforcement, nextGoLive, nextRoutes, nextRegisters, nextConnections, nextProviders] = await Promise.all([
        api.getFiscalTaxProfile(currentOrganization.id, accessToken).catch((caught) => {
          if (caught instanceof ApiError && caught.status === 404) return null;
          throw caught;
        }),
        api.getFiscalReadiness(currentOrganization.id, accessToken),
        api.getFiscalEnforcement(currentLocation.id, currentOrganization.id, accessToken),
        api.getFiscalGoLiveReadiness(currentLocation.id, currentOrganization.id, accessToken),
        api.listFiscalRoutes(currentLocation.id, currentOrganization.id, accessToken),
        api.listPosRegisters(currentLocation.id, currentOrganization.id, accessToken),
        api.listIntegrationConnections(currentOrganization.id, accessToken),
        api.listIntegrationProviders(currentOrganization.id, accessToken),
      ]);
      if (requestId.current !== activeRequestId) return;
      setProfile(nextProfile);
      setReadiness(nextReadiness);
      setEnforcement(nextEnforcement);
      setGoLive(nextGoLive);
      setRoutes(nextRoutes);
      setRegisters(nextRegisters.filter((item) => item.is_active));
      setConnections(nextConnections.filter((item) => item.status === "ACTIVE"));
      setProviders(nextProviders);
      const defaultRegister = nextRegisters.find((item) => item.is_active)?.id ?? "";
      setRouteRegisterId((current) => nextRegisters.some((item) => item.id === current && item.is_active) ? current : defaultRegister);
      setLoadedOrganizationId(currentOrganization.id);
      setTax(nextProfile ? {
        country_code: nextProfile.country_code,
        tax_regime_code: nextProfile.tax_regime_code,
        vat_registered: nextProfile.vat_registered,
        default_vat_rate: nextProfile.default_vat_rate ?? "",
        effective_from: nextProfile.effective_from,
      } : newTaxDraft(currentOrganization.country_code));
    } catch (caught) {
      if (requestId.current === activeRequestId) setError(messageOf(caught));
    } finally {
      if (requestId.current === activeRequestId) setLoading(false);
    }
  }, [accessToken, currentLocation, currentOrganization, permissions.canReadFiscal, permissions.loading]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  useEffect(() => {
    let cancelled = false;
    async function loadBindings() {
      await Promise.resolve();
      if (!accessToken || !currentOrganization || !routeRegisterId || (!permissions.canUseTerminal && !permissions.canManageTerminal)) {
        setTerminalBindings([]);
        return;
      }
      try {
        const values = await api.listTerminalBindings(routeRegisterId, currentOrganization.id, accessToken);
        if (!cancelled) setTerminalBindings(values);
      } catch {
        if (!cancelled) setTerminalBindings([]);
      }
    }
    void loadBindings();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, permissions.canManageTerminal, permissions.canUseTerminal, routeRegisterId]);

  const fiscalProviderCodes = useMemo(() => new Set(providers.filter((item) => item.capabilities.includes("FISCAL")).map((item) => item.code)), [providers]);
  const paymentProviderCodes = useMemo(() => new Set(providers.filter((item) => item.capabilities.includes("PAYMENT")).map((item) => item.code)), [providers]);
  const fiscalConnections = connections.filter((item) => fiscalProviderCodes.has(item.provider_code));
  const paymentConnections = connections.filter((item) => paymentProviderCodes.has(item.provider_code));
  const routeConnections = routeSourceMode === "EXTERNAL_KKM" ? fiscalConnections : paymentConnections;

  async function saveTax(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !permissions.canWriteFiscal) return;
    const rate = tax.default_vat_rate.trim();
    if (!tax.tax_regime_code.trim() || (tax.vat_registered && (!validRate(rate) || !/[1-9]/.test(rate)))) {
      setError("Enter a tax regime and a positive VAT rate for a VAT-registered organization.");
      return;
    }
    setSaving(true);
    const requestOrganizationId = currentOrganization.id;
    setError("");
    setMessage("");
    try {
      await api.updateFiscalTaxProfile({
        country_code: tax.country_code.trim().toUpperCase(),
        tax_regime_code: tax.tax_regime_code.trim(),
        vat_registered: tax.vat_registered,
        default_vat_rate: tax.vat_registered ? rate : null,
        effective_from: tax.effective_from,
      }, currentOrganization.id, accessToken);
      if (activeOrganizationId.current !== requestOrganizationId) return;
      setMessage("Tax profile saved as a new effective version.");
      await load();
    } catch (caught) {
      if (activeOrganizationId.current === requestOrganizationId) setError(messageOf(caught));
    } finally {
      if (activeOrganizationId.current === requestOrganizationId) setSaving(false);
    }
  }

  async function editVariant(id: string, name: string) {
    if (!accessToken || !currentOrganization) return;
    setSaving(true);
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const requestOrganizationId = currentOrganization.id;
    setError("");
    try {
      const value = await api.getFiscalVariantProfile(id, currentOrganization.id, accessToken).catch((caught) => {
        if (caught instanceof ApiError && caught.status === 404) return null;
        throw caught;
      });
      if (activeOrganizationId.current !== requestOrganizationId) return;
      setVariantId(id);
      setVariantName(name);
      setVariantProfile(value);
      setNktQuery("");
      setNktResults([]);
      setSelectedNtin("");
      setVariant(value ? {
        fiscal_name: value.fiscal_name,
        nkt_code: value.nkt_code,
        nkt_code_type: value.nkt_code_type,
        fiscal_unit_code: value.fiscal_unit_code,
        vat_rate_override: value.vat_rate_override,
        requires_marking: value.requires_marking,
      } : { ...emptyVariant, fiscal_name: name });
    } catch (caught) {
      if (activeOrganizationId.current === requestOrganizationId) setError(messageOf(caught));
    } finally {
      if (activeOrganizationId.current === requestOrganizationId) setSaving(false);
    }
  }

  async function saveVariant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !variantId || !permissions.canWriteFiscal) return;
    const override = variant.vat_rate_override?.trim() || null;
    if (!variant.fiscal_name.trim() || !variant.fiscal_unit_code.trim() || (override !== null && !validRate(override))) {
      setError("Fiscal name and unit are required. VAT override must be zero or greater.");
      return;
    }
    setSaving(true);
    const requestOrganizationId = currentOrganization.id;
    setError("");
    try {
      await api.updateFiscalVariantProfile(variantId, {
        fiscal_name: variant.fiscal_name.trim(),
        nkt_code: variant.nkt_code?.trim() || null,
        nkt_code_type: variant.nkt_code_type?.trim() || null,
        fiscal_unit_code: variant.fiscal_unit_code.trim(),
        vat_rate_override: override,
        requires_marking: variant.requires_marking,
      }, currentOrganization.id, accessToken);
      if (activeOrganizationId.current !== requestOrganizationId) return;
      setVariantId("");
      setMessage(`${variantName} fiscal profile saved.`);
      await load();
    } catch (caught) {
      if (activeOrganizationId.current === requestOrganizationId) setError(messageOf(caught));
    } finally {
      if (activeOrganizationId.current === requestOrganizationId) setSaving(false);
    }
  }

  function closeVariant() {
    setVariantId("");
    setVariantProfile(null);
    queueMicrotask(() => returnFocus.current?.focus());
  }

  async function searchNkt() {
    if (!accessToken || !currentOrganization || !nktQuery.trim()) return;
    setNktBusy(true);
    setError("");
    try {
      const query = nktQuery.trim();
      const results = nktMode === "NTIN"
        ? [await api.getNktByNtin(query, currentOrganization.id, accessToken)]
        : nktMode === "GTIN"
          ? await api.getNktByGtin(query, currentOrganization.id, accessToken)
          : await api.searchNkt(query, currentOrganization.id, accessToken);
      setNktResults(results);
      setSelectedNtin(results.length === 1 ? results[0].ntin : "");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        setNktResults([]);
        setSelectedNtin("");
      } else setError(messageOf(caught));
    } finally {
      setNktBusy(false);
    }
  }

  async function linkNkt() {
    if (!accessToken || !currentOrganization || !variantId || !selectedNtin || !permissions.canWriteFiscal) return;
    setNktBusy(true);
    setError("");
    try {
      const value = await api.linkFiscalVariantNkt(variantId, selectedNtin, currentOrganization.id, accessToken);
      setVariantProfile(value);
      setVariant((current) => ({ ...current, nkt_code: value.nkt_code, nkt_code_type: value.nkt_code_type }));
      setMessage(`${variantName} linked to verified NKT product.`);
      setReadiness(await api.getFiscalReadiness(currentOrganization.id, accessToken));
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setNktBusy(false);
    }
  }

  async function refreshNkt() {
    if (!accessToken || !currentOrganization || !variantId || !permissions.canWriteFiscal) return;
    setNktBusy(true);
    setError("");
    try {
      const value = await api.refreshFiscalVariantNkt(variantId, currentOrganization.id, accessToken);
      setVariantProfile(value);
      setVariant((current) => ({ ...current, nkt_code: value.nkt_code, nkt_code_type: value.nkt_code_type }));
      setMessage(`${variantName} NKT mapping refreshed for future sales.`);
      setReadiness(await api.getFiscalReadiness(currentOrganization.id, accessToken));
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setNktBusy(false);
    }
  }

  async function saveEnforcement(mode: FiscalEnforcementMode) {
    if (!accessToken || !currentOrganization || !currentLocation || !permissions.canWriteFiscal) return;
    setSaving(true);
    setError("");
    try {
      setEnforcement(await api.updateFiscalEnforcement(currentLocation.id, mode, currentOrganization.id, accessToken));
      setMessage(`Fiscal mode for ${currentLocation.name} updated.`);
      setGoLive(await api.getFiscalGoLiveReadiness(currentLocation.id, currentOrganization.id, accessToken));
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  async function createRoute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !currentLocation || !routeRegisterId || !routeConnectionId || !permissions.canWriteFiscal) return;
    setSaving(true);
    setError("");
    try {
      const route = await api.createFiscalRoute({ location_id: currentLocation.id, register_id: routeRegisterId, provider_connection_id: routeConnectionId, source_mode: routeSourceMode, is_active: true }, currentOrganization.id, accessToken);
      setRoutes((current) => [...current.filter((item) => item.id !== route.id), route]);
      setMessage("Fiscal route activated. Beanly prevents a second active route for this register.");
      setGoLive(await api.getFiscalGoLiveReadiness(currentLocation.id, currentOrganization.id, accessToken));
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  async function deactivateRoute(route: FiscalRoute) {
    if (!accessToken || !currentOrganization || !permissions.canWriteFiscal) return;
    setSaving(true);
    setError("");
    try {
      const value = await api.updateFiscalRoute(route.id, { is_active: false }, currentOrganization.id, accessToken);
      setRoutes((current) => current.map((item) => item.id === value.id ? value : item));
      setMessage("Fiscal route disabled.");
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  async function createTerminalBinding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !currentLocation || !routeRegisterId || !terminalConnectionId || !permissions.canManageTerminal) return;
    const connection = paymentConnections.find((item) => item.id === terminalConnectionId);
    if (!connection) return;
    setSaving(true);
    setError("");
    try {
      const binding = await api.createTerminalBinding({ connection_id: connection.id, location_id: currentLocation.id, register_id: routeRegisterId, provider_code: connection.provider_code, external_terminal_id: externalTerminalId.trim() || null, is_active: true }, currentOrganization.id, accessToken);
      setTerminalBindings((current) => [...current.filter((item) => item.id !== binding.id), binding]);
      setExternalTerminalId("");
      setMessage("Payment terminal bound. No provider secret was sent to the browser.");
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  if (permissions.loading || loading) return <div className="fiscal-state">Loading fiscal settings…</div>;
  if (permissions.canReadFiscal && loadedOrganizationId !== currentOrganization?.id) return <div className="fiscal-state" role="alert"><strong>Fiscal settings could not be loaded</strong><span>{error || "An online sign-in is required."}</span><button className="secondary-button" type="button" onClick={() => void load()}>Try again</button></div>;
  if (!permissions.canReadFiscal) return <div className="fiscal-state"><strong>Fiscal settings access required</strong><span>Your role cannot view tax or fiscal configuration.</span></div>;

  return (
    <>
      <header className="settings-header"><h1>Fiscal &amp; Taxes</h1><p>Organization tax identity and receipt readiness. Beanly does not provide tax advice.</p></header>
      {message && <div className="menu-flash" role="status"><Check aria-hidden="true" />{message}</div>}
      {error && <div className="fiscal-alert" role="alert"><CircleAlert aria-hidden="true" />{error}</div>}
      <section className="fiscal-readiness" aria-labelledby="readiness-title">
        <div><span className="pos-eyebrow">Configuration</span><h2 id="readiness-title">Fiscal readiness</h2><p>{readiness?.ready ? "Ready for complete fiscal sale snapshots." : "Finish the items below before fiscalization."}</p></div>
        <strong aria-label={`${readiness?.readiness_percent ?? 0} percent ready`}>{readiness?.readiness_percent ?? 0}%</strong>
        <div className="fiscal-progress" aria-hidden="true"><i style={{ width: `${readiness?.readiness_percent ?? 0}%` }} /></div>
        <ul>
          <li className={readiness?.tax_profile === "COMPLETE" ? "is-complete" : ""}><span>{readiness?.tax_profile === "COMPLETE" ? "✓" : "!"}</span>Tax profile</li>
          <li className={readiness?.location === "COMPLETE" ? "is-complete" : ""}><span>{readiness?.location === "COMPLETE" ? "✓" : "!"}</span>Location</li>
          <li className={readiness?.unmapped_variants.length === 0 ? "is-complete" : ""}><span>{readiness?.unmapped_variants.length === 0 ? "✓" : "!"}</span>NKT mappings</li>
        </ul>
      </section>

      <section className="fiscal-card fiscal-live-card">
        <div className="fiscal-card-heading"><div><h2>{currentLocation?.name} fiscal mode</h2><p>Live mode blocks checkout before money is taken when fiscal preflight fails.</p></div><span>{enforcement?.mode ?? "DISABLED"}</span></div>
        <div className="fiscal-mode-actions" role="group" aria-label="Fiscal enforcement mode">
          <button className={enforcement?.mode === "DISABLED" ? "is-active" : ""} disabled={!permissions.canWriteFiscal || saving} type="button" onClick={() => void saveEnforcement("DISABLED")}>Disabled</button>
          <button className={enforcement?.mode === "TEST" ? "is-active" : ""} disabled={!permissions.canWriteFiscal || saving} type="button" onClick={() => void saveEnforcement("TEST")}>Test</button>
          <button className={enforcement?.mode === "LIVE_REQUIRED" ? "is-active" : ""} disabled={!permissions.canWriteFiscal || saving || !goLive?.ready} type="button" onClick={() => void saveEnforcement("LIVE_REQUIRED")}>Switch to production</button>
        </div>
        {!goLive?.ready && <p className="fiscal-advice">Production stays locked until every go-live check below passes.</p>}
        <div className="fiscal-checklist">{Object.entries(goLive?.checks ?? {}).map(([code, complete]) => <article className={complete ? "is-complete" : ""} key={code}><span aria-hidden="true">{complete ? "✓" : "!"}</span><div><strong>{labelFromCode(code)}</strong></div><em>{complete ? "COMPLETE" : "INCOMPLETE"}</em></article>)}</div>
      </section>

      <section className="fiscal-card">
        <div className="fiscal-card-heading"><div><h2>Fiscal routing</h2><p>One active fiscal source per register prevents duplicate receipts.</p></div><span>{routes.filter((item) => item.is_active).length} active</span></div>
        {routes.length > 0 && <div className="fiscal-route-list">{routes.map((route) => <article key={route.id}><div><strong>{registers.find((item) => item.id === route.register_id)?.name ?? "Register"}</strong><span>{route.source_mode === "EXTERNAL_KKM" ? "External KKM" : "Payment terminal KKM"} · {connections.find((item) => item.id === route.provider_connection_id)?.display_name ?? shortId(route.provider_connection_id)}</span></div><span className={route.is_active ? "is-active" : ""}>{route.is_active ? "Active" : "Disabled"}</span>{route.is_active && permissions.canWriteFiscal && <button className="secondary-button" disabled={saving} type="button" onClick={() => void deactivateRoute(route)}>Disable</button>}</article>)}</div>}
        {permissions.canWriteFiscal && <form className="fiscal-route-form" onSubmit={createRoute}>
          <label><span>Register</span><select required value={routeRegisterId} onChange={(event) => setRouteRegisterId(event.target.value)}><option value="">Select register</option>{registers.map((register) => <option key={register.id} value={register.id}>{register.name}</option>)}</select></label>
          <label><span>Fiscal source</span><select value={routeSourceMode} onChange={(event) => { setRouteSourceMode(event.target.value as FiscalRoute["source_mode"]); setRouteConnectionId(""); }}><option value="EXTERNAL_KKM">External KKM</option><option value="PAYMENT_TERMINAL_KKM">Payment terminal KKM</option></select></label>
          <label><span>Connection</span><select required value={routeConnectionId} onChange={(event) => setRouteConnectionId(event.target.value)}><option value="">Select connection</option>{routeConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.display_name}</option>)}</select></label>
          <button className="primary-button" disabled={saving || !routeRegisterId || !routeConnectionId} type="submit">Activate route</button>
        </form>}
      </section>

      {(permissions.canUseTerminal || permissions.canManageTerminal) && <section className="fiscal-card">
        <div className="fiscal-card-heading"><div><h2>Payment terminal</h2><p>Bindings expose only public terminal configuration. Provider secrets remain server-side.</p></div><ShieldCheck aria-hidden="true" /></div>
        <label className="fiscal-terminal-register"><span>Register</span><select value={routeRegisterId} onChange={(event) => setRouteRegisterId(event.target.value)}><option value="">Select register</option>{registers.map((register) => <option key={register.id} value={register.id}>{register.name}</option>)}</select></label>
        {terminalBindings.length > 0 && <div className="fiscal-terminal-bindings">{terminalBindings.map((binding) => <article key={binding.id}><div><strong>{binding.provider_code}</strong><span>{binding.external_terminal_id || "Provider-managed terminal"}</span></div><span className={binding.is_active ? "is-active" : ""}>{binding.is_active ? "Connected" : "Inactive"}</span></article>)}</div>}
        {permissions.canManageTerminal && <form className="fiscal-terminal-form" onSubmit={createTerminalBinding}>
          <label><span>Payment connection</span><select required value={terminalConnectionId} onChange={(event) => setTerminalConnectionId(event.target.value)}><option value="">Select connection</option>{paymentConnections.map((connection) => <option key={connection.id} value={connection.id}>{connection.display_name}</option>)}</select></label>
          <label><span>External terminal ID <small>Optional</small></span><input maxLength={255} value={externalTerminalId} onChange={(event) => setExternalTerminalId(event.target.value)} /></label>
          <button className="primary-button" disabled={saving || !routeRegisterId || !terminalConnectionId} type="submit">Bind terminal</button>
        </form>}
      </section>}

      <form className="fiscal-card" onSubmit={saveTax}>
        <div className="fiscal-card-heading"><div><h2>Organization tax profile</h2><p>Changes create a new effective version and do not rewrite past sales.</p></div>{profile && <span>Effective {profile.effective_from}</span>}</div>
        <div className="fiscal-form-grid">
          <label><span>Country</span><input required maxLength={2} disabled={!permissions.canWriteFiscal} value={tax.country_code} onChange={(event) => setTax((current) => ({ ...current, country_code: event.target.value }))} /></label>
          <label><span>Tax regime</span><input required maxLength={64} list="tax-regimes" disabled={!permissions.canWriteFiscal} value={tax.tax_regime_code} onChange={(event) => setTax((current) => ({ ...current, tax_regime_code: event.target.value }))} /><datalist id="tax-regimes"><option value="SIMPLIFIED_DECLARATION">Simplified declaration</option><option value="GENERAL">General regime</option></datalist></label>
          <label><span>Effective from</span><input required type="date" disabled={!permissions.canWriteFiscal} value={tax.effective_from} onChange={(event) => setTax((current) => ({ ...current, effective_from: event.target.value }))} /></label>
          <label className="fiscal-check"><input type="checkbox" disabled={!permissions.canWriteFiscal} checked={tax.vat_registered} onChange={(event) => setTax((current) => ({ ...current, vat_registered: event.target.checked, default_vat_rate: event.target.checked && !current.default_vat_rate && current.country_code.toUpperCase() === "KZ" ? "16.00" : current.default_vat_rate }))} /><span>VAT registered</span></label>
          {tax.vat_registered && <label><span>Default VAT rate (%)</span><input required inputMode="decimal" disabled={!permissions.canWriteFiscal} value={tax.default_vat_rate} onChange={(event) => setTax((current) => ({ ...current, default_vat_rate: event.target.value }))} /></label>}
        </div>
        <p className="fiscal-advice">Verify these settings with your accountant. The current Kazakhstan rate shown as a default remains editable.</p>
        {permissions.canWriteFiscal && <div className="fiscal-actions"><button className="primary-button" disabled={saving} type="submit">{saving ? "Saving…" : "Save tax profile"}</button></div>}
      </form>

      <section className="fiscal-card">
        <div className="fiscal-card-heading"><div><h2>Variant fiscal profiles</h2><p>Receipt name, NKT identity, unit and marking requirements per sold variant.</p></div><span>{readiness?.unmapped_variants.length ?? 0} need attention</span></div>
        {linkedVariantId && !readiness?.unmapped_variants.some((item) => item.variant_id === linkedVariantId) && <div className="fiscal-variant-list fiscal-linked-variant"><article><div><strong>{linkedVariantName}</strong><span>Linked from Menu</span></div><button className="secondary-button" disabled={saving} type="button" onClick={() => void editVariant(linkedVariantId, linkedVariantName)}><Pencil aria-hidden="true" />{permissions.canWriteFiscal ? "Configure" : "View"}</button></article></div>}
        {readiness?.unmapped_variants.length ? <div className="fiscal-variant-list">{readiness.unmapped_variants.map((item) => <article key={item.variant_id}><div><strong>{item.name}</strong><span>{item.reason || "Fiscal profile incomplete"}</span></div><button className="secondary-button" disabled={saving} type="button" onClick={() => void editVariant(item.variant_id, item.name)}><Pencil aria-hidden="true" />{permissions.canWriteFiscal ? "Configure" : "View"}</button></article>)}</div> : !linkedVariantId && <div className="fiscal-empty"><Check aria-hidden="true" /><strong>All active variants are mapped</strong><span>Open any Menu variant to review its fiscal profile.</span></div>}
      </section>

      {variantId && (
        <div className="modal-backdrop" role="presentation">
          <form className="modal-card fiscal-variant-modal" role="dialog" aria-modal="true" aria-labelledby="variant-fiscal-title" onKeyDown={(event) => { if (event.key === "Escape") closeVariant(); else trapDialogFocus(event); }} onSubmit={saveVariant}>
            <button className="modal-close" disabled={saving} type="button" aria-label="Close fiscal profile" onClick={closeVariant}><X /></button>
            <span className="pos-eyebrow">Variant fiscal profile</span><h2 id="variant-fiscal-title">{variantName}</h2>
            <label className="modal-field"><span>Fiscal receipt name</span><input autoFocus required maxLength={300} disabled={!permissions.canWriteFiscal} value={variant.fiscal_name} onChange={(event) => setVariant((current) => ({ ...current, fiscal_name: event.target.value }))} /></label>
            <section className="fiscal-nkt-mapping" aria-labelledby="nkt-mapping-title">
              <div className="fiscal-nkt-heading"><div><h3 id="nkt-mapping-title">National Catalog</h3><p>Cache search is local. Use exact NTIN/GTIN lookup for the official catalog.</p></div>{variantProfile?.nkt_verified_at && <span><Check aria-hidden="true" />NKT verified</span>}</div>
              {variantProfile?.nkt_code && <div className="fiscal-nkt-linked"><div><span>NTIN</span><strong>{variantProfile.nkt_code}</strong></div><div><span>Last verified</span><strong>{formatDate(variantProfile.nkt_verified_at)}</strong></div>{permissions.canWriteFiscal && <button className="secondary-button" disabled={nktBusy} type="button" onClick={() => void refreshNkt()}><RefreshCcw className={nktBusy ? "is-spinning" : ""} aria-hidden="true" />Refresh</button>}</div>}
              <div className="fiscal-nkt-search">
                <select aria-label="Catalog lookup type" value={nktMode} onChange={(event) => { setNktMode(event.target.value as typeof nktMode); setNktResults([]); setSelectedNtin(""); }}><option value="CACHE">Cached catalog</option><option value="NTIN">Exact NTIN</option><option value="GTIN">Exact GTIN</option></select>
                <input aria-label="Catalog search" maxLength={300} placeholder={nktMode === "CACHE" ? "Search cached National Catalog" : `Enter exact ${nktMode}`} value={nktQuery} onChange={(event) => setNktQuery(event.target.value)} />
                <button className="secondary-button" disabled={nktBusy || !nktQuery.trim()} type="button" onClick={() => void searchNkt()}><Search aria-hidden="true" />{nktBusy ? "Searching…" : "Search"}</button>
              </div>
              {nktQuery && !nktBusy && nktResults.length === 0 && <p className="fiscal-nkt-empty">No cached match. Use an exact NTIN or GTIN lookup when available.</p>}
              {nktResults.length > 0 && <div className="fiscal-nkt-results" role="radiogroup" aria-label="National Catalog results">{nktResults.map((result) => <label key={result.external_id}><input type="radio" name="nkt_result" checked={selectedNtin === result.ntin} onChange={() => setSelectedNtin(result.ntin)} /><span><strong>{result.name_ru || result.name_kk || "Unnamed NKT product"}</strong><small>NTIN: {result.ntin}{result.unit_code ? ` · ${result.unit_code}` : ""}</small></span></label>)}</div>}
              {!variantProfile && permissions.canWriteFiscal && <p className="fiscal-nkt-empty">Save the fiscal profile first, then reopen it to link an NKT product.</p>}
              {variantProfile && permissions.canWriteFiscal && selectedNtin && <button className="primary-button fiscal-nkt-link" disabled={nktBusy} type="button" onClick={() => void linkNkt()}><Link2 aria-hidden="true" />Link selected product</button>}
            </section>
            <label className="modal-field"><span>Fiscal unit</span><input required maxLength={50} list="fiscal-units" disabled={!permissions.canWriteFiscal} value={variant.fiscal_unit_code} onChange={(event) => setVariant((current) => ({ ...current, fiscal_unit_code: event.target.value }))} /><datalist id="fiscal-units"><option value="pcs" /><option value="g" /><option value="kg" /><option value="ml" /><option value="l" /></datalist></label>
            <label className="modal-field"><span>VAT override (%) <small>Blank inherits organization</small></span><input inputMode="decimal" disabled={!permissions.canWriteFiscal} value={variant.vat_rate_override ?? ""} onChange={(event) => setVariant((current) => ({ ...current, vat_rate_override: event.target.value || null }))} /></label>
            <label className="fiscal-check"><input type="checkbox" disabled={!permissions.canWriteFiscal} checked={variant.requires_marking} onChange={(event) => setVariant((current) => ({ ...current, requires_marking: event.target.checked }))} /><span>Requires product marking codes</span></label>
            <div className="modal-actions"><button className="secondary-button" disabled={saving} type="button" onClick={closeVariant}>Close</button>{permissions.canWriteFiscal && <button className="primary-button" disabled={saving} type="submit">{saving ? "Saving…" : "Save fiscal profile"}</button>}</div>
          </form>
        </div>
      )}
    </>
  );
}

function newTaxDraft(country: string): TaxDraft {
  return { country_code: country || "KZ", tax_regime_code: "", vat_registered: false, default_vat_rate: "", effective_from: localDateInput() };
}
function validRate(value: string) { return /^\d+(?:\.\d{1,4})?$/.test(value) && Number(value) >= 0; }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Something went wrong. Please try again."; }
function shortId(value: string) { return value.length > 12 ? `${value.slice(0, 8)}…` : value; }
function formatDate(value: string | null) { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value)) : "Not verified"; }
function labelFromCode(code: string) { const value = code.replaceAll("_", " ").toLowerCase(); return value.charAt(0).toUpperCase() + value.slice(1); }
