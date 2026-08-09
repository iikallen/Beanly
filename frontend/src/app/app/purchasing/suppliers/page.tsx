"use client";

import { ChevronRight, Plus, Search, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type Supplier, type SupplierInput } from "@/lib/api";

export default function SuppliersPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canCreate } = usePurchasingPermissions();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [query, setQuery] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization) return;
    setLoading(true);
    setError("");
    try {
      setSuppliers(await api.listSuppliers(currentOrganization.id, accessToken, includeInactive));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load suppliers");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization, includeInactive]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const visibleSuppliers = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return suppliers
      .filter((supplier) => !needle || [supplier.name, supplier.contact_name, supplier.email, supplier.phone].some((value) => value?.toLocaleLowerCase().includes(needle)))
      .sort((left, right) => left.name.localeCompare(right.name));
  }, [query, suppliers]);

  return (
    <>
      <header className="purchasing-header">
        <div><h1>Suppliers</h1><p>Manage the companies that provide your stock.</p></div>
        {canCreate && <button className="purchasing-primary" type="button" onClick={() => dialog.current?.showModal()}><Plus aria-hidden="true" />Add supplier</button>}
      </header>
      <div className="supplier-toolbar">
        <label className="purchasing-search"><span className="sr-only">Search suppliers</span><Search aria-hidden="true" /><input type="search" placeholder="Search suppliers" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <label className="supplier-inactive-toggle"><input type="checkbox" checked={includeInactive} onChange={(event) => setIncludeInactive(event.target.checked)} /><span>Show inactive</span></label>
      </div>
      {error ? (
        <div className="purchasing-state is-error" role="alert"><strong>Suppliers could not be loaded.</strong><span>{error}</span></div>
      ) : loading ? (
        <div className="purchasing-state" aria-live="polite">Loading suppliers…</div>
      ) : visibleSuppliers.length === 0 ? (
        <div className="purchasing-state"><strong>No suppliers found</strong><span>{query ? "Try a different search." : "Add your first supplier to begin purchasing."}</span></div>
      ) : (
        <div className="supplier-list">
          <div className="supplier-list-head" aria-hidden="true"><span>Supplier</span><span>Contact</span><span>Status</span><span /></div>
          {visibleSuppliers.map((supplier) => (
            <Link className="supplier-row" key={supplier.id} href={`/app/purchasing/suppliers/${supplier.id}`}>
              <span><strong>{supplier.name}</strong>{supplier.tax_id && <small>{supplier.tax_id}</small>}</span>
              <span><strong>{supplier.contact_name ?? "—"}</strong><small>{supplier.email ?? supplier.phone ?? "No contact details"}</small></span>
              <span className={supplier.is_active ? "purchasing-status status-posted" : "purchasing-status status-reversed"}>{supplier.is_active ? "Active" : "Inactive"}</span>
              <ChevronRight aria-hidden="true" />
            </Link>
          ))}
        </div>
      )}

      <dialog className="supplier-dialog" ref={dialog} aria-labelledby="add-supplier-title" onClick={(event) => { if (event.target === dialog.current) dialog.current.close(); }}>
        <button className="modal-close" type="button" aria-label="Close" onClick={() => dialog.current?.close()}><X aria-hidden="true" /></button>
        <h2 id="add-supplier-title">Add supplier</h2>
        <SupplierCreateForm
          onCancel={() => dialog.current?.close()}
          onCreated={async () => {
            dialog.current?.close();
            await load();
          }}
        />
      </dialog>
    </>
  );
}

function SupplierCreateForm({ onCancel, onCreated }: { onCancel: () => void; onCreated: () => Promise<void> }) {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization) return;
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
    setSubmitting(true);
    setError("");
    try {
      await api.createSupplier(input, currentOrganization.id, accessToken);
      await onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create supplier");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="supplier-form-grid">
        <label className="purchase-field supplier-name-field"><span>Name</span><input name="name" maxLength={200} required autoFocus /></label>
        <label className="purchase-field"><span>Contact name</span><input name="contact_name" maxLength={150} /></label>
        <label className="purchase-field"><span>Phone</span><input name="phone" type="tel" maxLength={50} /></label>
        <label className="purchase-field"><span>Email</span><input name="email" type="email" maxLength={255} /></label>
        <label className="purchase-field"><span>Tax ID</span><input name="tax_id" maxLength={100} /></label>
        <label className="purchase-field"><span>Address</span><input name="address" /></label>
        <label className="purchase-field supplier-name-field"><span>Note</span><textarea name="note" maxLength={1000} /></label>
      </div>
      <div className="form-message purchase-error" role="alert">{error}</div>
      <div className="modal-actions"><button className="secondary-button" type="button" onClick={onCancel}>Cancel</button><button className="purchasing-primary" type="submit" disabled={submitting}>{submitting ? "Adding…" : "Add supplier"}</button></div>
    </form>
  );
}

function optional(data: FormData, name: string) {
  const value = String(data.get(name) ?? "").trim();
  return value || null;
}
