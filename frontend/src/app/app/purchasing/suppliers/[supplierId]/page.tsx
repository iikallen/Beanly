"use client";

import { ArrowLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type PurchaseOrder, type Supplier, type SupplierInput } from "@/lib/api";
import {
  formatMoneyMinor,
  formatPurchaseDate,
  formatPurchaseStatus,
  statusClass,
} from "@/lib/purchasing";

export default function SupplierDetailPage() {
  const { supplierId } = useParams<{ supplierId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canUpdate } = usePurchasingPermissions();
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization) return;
    setLoading(true);
    setError("");
    try {
      const [nextSupplier, nextOrders] = await Promise.all([
        api.getSupplier(supplierId, currentOrganization.id, accessToken),
        api.listPurchaseOrders(currentOrganization.id, accessToken, { supplierId }),
      ]);
      setSupplier(nextSupplier);
      setOrders(nextOrders);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load supplier");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization, supplierId]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !supplier) return;
    const data = new FormData(event.currentTarget);
    const input: SupplierInput = {
      name: String(data.get("name") ?? "").trim(),
      contact_name: optional(data, "contact_name"),
      phone: optional(data, "phone"),
      email: optional(data, "email"),
      tax_id: optional(data, "tax_id"),
      address: optional(data, "address"),
      note: optional(data, "note"),
    };
    setWorking(true);
    setError("");
    try {
      setSupplier(await api.updateSupplier(supplier.id, input, currentOrganization.id, accessToken));
      setEditing(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update supplier");
    } finally {
      setWorking(false);
    }
  }

  async function deactivate() {
    if (!accessToken || !currentOrganization || !supplier) return;
    if (!window.confirm(`Deactivate ${supplier.name}? Historical purchases will be kept.`)) return;
    setWorking(true);
    setError("");
    try {
      setSupplier(await api.deactivateSupplier(supplier.id, currentOrganization.id, accessToken));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to deactivate supplier");
    } finally {
      setWorking(false);
    }
  }

  if (loading) return <div className="purchasing-state">Loading supplier…</div>;
  if (error && !supplier) return <div className="purchasing-state is-error" role="alert"><strong>Supplier could not be loaded.</strong><span>{error}</span><Link href="/app/purchasing/suppliers">Back to suppliers</Link></div>;
  if (!supplier) return null;

  return (
    <>
      <Link className="purchasing-back" href="/app/purchasing/suppliers"><ArrowLeft aria-hidden="true" />Suppliers</Link>
      <header className="purchasing-header order-detail-header">
        <div><h1>{supplier.name}</h1><p>{supplier.is_active ? "Active supplier" : "Inactive supplier · retained for purchase history"}</p></div>
        {canUpdate && supplier.is_active && !editing && <div className="purchase-header-actions"><button className="secondary-button" type="button" onClick={() => setEditing(true)}>Edit supplier</button><button className="secondary-button is-danger" type="button" disabled={working} onClick={() => void deactivate()}>Deactivate</button></div>}
      </header>
      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}

      {editing ? (
        <form className="supplier-detail-form" onSubmit={save}>
          <div className="supplier-form-grid">
            <label className="purchase-field supplier-name-field"><span>Name</span><input name="name" maxLength={200} defaultValue={supplier.name} required /></label>
            <label className="purchase-field"><span>Contact name</span><input name="contact_name" maxLength={150} defaultValue={supplier.contact_name ?? ""} /></label>
            <label className="purchase-field"><span>Phone</span><input name="phone" type="tel" maxLength={50} defaultValue={supplier.phone ?? ""} /></label>
            <label className="purchase-field"><span>Email</span><input name="email" type="email" maxLength={255} defaultValue={supplier.email ?? ""} /></label>
            <label className="purchase-field"><span>Tax ID</span><input name="tax_id" maxLength={100} defaultValue={supplier.tax_id ?? ""} /></label>
            <label className="purchase-field"><span>Address</span><input name="address" defaultValue={supplier.address ?? ""} /></label>
            <label className="purchase-field supplier-name-field"><span>Note</span><textarea name="note" maxLength={1000} defaultValue={supplier.note ?? ""} /></label>
          </div>
          <div className="purchase-form-actions compact"><button className="secondary-button" type="button" onClick={() => setEditing(false)}>Cancel</button><button className="purchasing-primary" type="submit" disabled={working}>{working ? "Saving…" : "Save changes"}</button></div>
        </form>
      ) : (
        <dl className="supplier-details">
          <div><dt>Contact</dt><dd>{supplier.contact_name ?? "—"}</dd></div>
          <div><dt>Phone</dt><dd>{supplier.phone ? <a href={`tel:${supplier.phone}`}>{supplier.phone}</a> : "—"}</dd></div>
          <div><dt>Email</dt><dd>{supplier.email ? <a href={`mailto:${supplier.email}`}>{supplier.email}</a> : "—"}</dd></div>
          <div><dt>Tax ID</dt><dd>{supplier.tax_id ?? "—"}</dd></div>
          <div><dt>Address</dt><dd>{supplier.address ?? "—"}</dd></div>
          {supplier.note && <div className="supplier-note"><dt>Note</dt><dd>{supplier.note}</dd></div>}
        </dl>
      )}

      <section className="purchase-related supplier-purchases">
        <div className="purchase-section-heading"><div><h2>Purchases</h2><p>Purchase orders linked to this supplier.</p></div><span>{orders.length}</span></div>
        {orders.length === 0 ? <div className="purchasing-state is-compact">No purchase orders yet.</div> : <div className="purchase-related-list">{orders.map((order) => <Link key={order.id} href={`/app/purchasing/orders/${order.id}`}><strong>{order.number}</strong><span>{formatMoneyMinor(order.total_minor, order.currency_code)} · {formatPurchaseDate(order.expected_at)}</span><span className={statusClass(order.status)}>{formatPurchaseStatus(order.status)}</span><ChevronRight aria-hidden="true" /></Link>)}</div>}
      </section>
    </>
  );
}

function optional(data: FormData, name: string) {
  const value = String(data.get(name) ?? "").trim();
  return value || null;
}
