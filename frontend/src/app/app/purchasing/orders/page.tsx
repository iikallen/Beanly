"use client";

import { ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import {
  api,
  type PurchaseOrder,
  type PurchaseOrderStatus,
  type Supplier,
} from "@/lib/api";
import {
  formatMoneyMinor,
  formatPurchaseDate,
  formatPurchaseStatus,
  orderTotalMinor,
  statusClass,
} from "@/lib/purchasing";

export default function PurchaseOrdersPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canCreate } = usePurchasingPermissions();
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [status, setStatus] = useState<PurchaseOrderStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [[], []] as [PurchaseOrder[], Supplier[]];
      setLoading(true);
      setError("");
      return Promise.all([
        api.listPurchaseOrders(currentOrganization.id, accessToken, {
          locationId: currentLocation.id,
          supplierId: supplierId || undefined,
          status,
        }),
        api.listSuppliers(currentOrganization.id, accessToken, true),
      ]);
    })
      .then(([nextOrders, nextSuppliers]) => {
        if (cancelled) return;
        setOrders(nextOrders);
        setSuppliers(nextSuppliers);
      })
      .catch((caught) => {
        if (!cancelled) {
          setOrders([]);
          setError(caught instanceof Error ? caught.message : "Unable to load purchase orders");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, status, supplierId]);

  const supplierNames = useMemo(
    () => new Map(suppliers.map((supplier) => [supplier.id, supplier.name])),
    [suppliers],
  );

  return (
    <>
      <header className="purchasing-header">
        <div>
          <h1>Purchase Orders</h1>
          <p>Plan orders and track deliveries.</p>
        </div>
        {canCreate && (
          <Link className="purchasing-primary" href="/app/purchasing/orders/new">
            <Plus aria-hidden="true" />
            New purchase order
          </Link>
        )}
      </header>

      <div className="purchasing-filters">
        <label>
          <span className="sr-only">Supplier</span>
          <select value={supplierId} onChange={(event) => setSupplierId(event.target.value)}>
            <option value="">Supplier</option>
            {suppliers.map((supplier) => (
              <option key={supplier.id} value={supplier.id}>{supplier.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Status</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as PurchaseOrderStatus | "")}
          >
            <option value="">Status</option>
            <option value="DRAFT">Draft</option>
            <option value="ORDERED">Ordered</option>
            <option value="PARTIALLY_RECEIVED">Partially received</option>
            <option value="RECEIVED">Received</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
        </label>
      </div>

      {error ? (
        <div className="purchasing-state is-error" role="alert">
          <strong>Purchase orders could not be loaded.</strong>
          <span>{error}</span>
        </div>
      ) : loading ? (
        <div className="purchasing-state" aria-live="polite">Loading purchase orders…</div>
      ) : orders.length === 0 ? (
        <div className="purchasing-state">
          <strong>No purchase orders found</strong>
          <span>Create an order or change the selected filters.</span>
        </div>
      ) : (
        <div className="purchasing-table-wrap" tabIndex={0} aria-label="Purchase orders table">
          <table className="purchasing-table orders-table">
            <caption className="sr-only">Purchase orders for the selected location</caption>
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col">Supplier</th>
                <th scope="col">Total</th>
                <th scope="col">Status</th>
                <th scope="col">Expected</th>
                <th scope="col"><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id}>
                  <td><Link href={`/app/purchasing/orders/${order.id}`}>{order.number}</Link></td>
                  <td>{order.supplier_name ?? supplierNames.get(order.supplier_id) ?? "Unknown supplier"}</td>
                  <td>{formatMoneyMinor(order.total_minor ?? orderTotalMinor(order.lines ?? []), order.currency_code)}</td>
                  <td><span className={statusClass(order.status)}>{formatPurchaseStatus(order.status)}</span></td>
                  <td>{formatPurchaseDate(order.expected_at)}</td>
                  <td>
                    <Link className="purchasing-row-link" href={`/app/purchasing/orders/${order.id}`} aria-label={`Open ${order.number}`}>
                      <ChevronRight aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
