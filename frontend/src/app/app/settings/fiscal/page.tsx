"use client";

import { Check, CircleAlert, Pencil, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useIntegrationPermissions } from "@/hooks/use-integration-permissions";
import { ApiError, api, type FiscalReadiness, type FiscalTaxProfile, type FiscalVariantProfile } from "@/lib/api";
import { localDateInput } from "@/lib/dashboard";
import { trapDialogFocus } from "@/lib/dialog";

type TaxDraft = Pick<FiscalTaxProfile, "country_code" | "tax_regime_code" | "vat_registered" | "effective_from"> & { default_vat_rate: string };
type VariantDraft = Pick<FiscalVariantProfile, "fiscal_name" | "nkt_code" | "nkt_code_type" | "fiscal_unit_code" | "vat_rate_override" | "requires_marking">;

const emptyVariant: VariantDraft = { fiscal_name: "", nkt_code: null, nkt_code_type: null, fiscal_unit_code: "pcs", vat_rate_override: null, requires_marking: false };

export default function FiscalSettingsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
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
    if (!accessToken || !currentOrganization || permissions.loading || !permissions.canReadFiscal) {
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
      const [nextProfile, nextReadiness] = await Promise.all([
        api.getFiscalTaxProfile(currentOrganization.id, accessToken).catch((caught) => {
          if (caught instanceof ApiError && caught.status === 404) return null;
          throw caught;
        }),
        api.getFiscalReadiness(currentOrganization.id, accessToken),
      ]);
      if (requestId.current !== activeRequestId) return;
      setProfile(nextProfile);
      setReadiness(nextReadiness);
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
  }, [accessToken, currentOrganization, permissions.canReadFiscal, permissions.loading]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

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
    queueMicrotask(() => returnFocus.current?.focus());
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
        </ul>
      </section>

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
            <label className="modal-field"><span>NKT code <small>Required for complete readiness</small></span><input maxLength={100} disabled={!permissions.canWriteFiscal} value={variant.nkt_code ?? ""} onChange={(event) => setVariant((current) => ({ ...current, nkt_code: event.target.value || null }))} /></label>
            <label className="modal-field"><span>NKT code type <small>Optional</small></span><input maxLength={20} disabled={!permissions.canWriteFiscal} value={variant.nkt_code_type ?? ""} onChange={(event) => setVariant((current) => ({ ...current, nkt_code_type: event.target.value || null }))} /></label>
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
