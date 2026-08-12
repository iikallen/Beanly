"use client";

import { ChevronDown, ChevronRight, Search, TriangleAlert, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { ApiError, api, type StockRow, type WarehouseResponse } from "@/lib/api";
import {
  formatInventoryMoney,
  formatInventoryQuantity,
  formatUnitCost,
  isNegativeDecimal,
} from "@/lib/inventory";

export default function InventoryPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const {
    canAdjust,
    canCount,
    canImport,
    canTransfer,
    canWriteOff,
    loading: permissionsLoading,
  } = useInventoryPermissions();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [stock, setStock] = useState<StockRow[]>([]);
  const [totalValue, setTotalValue] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loadingWarehouses, setLoadingWarehouses] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [error, setError] = useState("");
  const [requestedWarehouse] = useState(() => searchParams.get("warehouse_id"));

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [];
      setLoadingWarehouses(true);
      setWarehouseId("");
      setStock([]);
      setTotalValue(null);
      setLoadingStock(false);
      setError("");
      return api.listInventoryWarehouses(currentOrganization.id, accessToken);
    })
      .then((available) => {
        if (cancelled) return;
        const local = available.filter(
          (warehouse) => warehouse.is_active && warehouse.location_id === currentLocation.id,
        );
        setWarehouses(local);
        setWarehouseId(
          local.find((warehouse) => warehouse.id === requestedWarehouse)?.id ??
          local[0]?.id ??
          "",
        );
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load warehouses");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingWarehouses(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, requestedWarehouse]);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || !warehouseId) return;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoadingStock(true);
      setStock([]);
      setTotalValue(null);
      setError("");
      void api.getInventoryValuation(currentOrganization.id, accessToken, {
        warehouseId,
        locationId: currentLocation.id,
      })
      .then((valuation) => ({
        rows: valuation.items,
        total: valuation.total_inventory_value,
      }))
      .catch(async (caught) => {
        if (!(caught instanceof ApiError) || caught.status !== 403) throw caught;
        const rows = await api.listStock(currentOrganization.id, accessToken, {
          warehouseId,
          locationId: currentLocation.id,
        });
        return { rows, total: null };
      })
      .then((result) => {
        if (!cancelled) {
          setStock(result.rows);
          setTotalValue(result.total);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setStock([]);
          setTotalValue(null);
          setError(caught instanceof Error ? caught.message : "Unable to load stock");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingStock(false);
      });
    });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, warehouseId]);

  const filteredStock = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return stock
      .filter((row) =>
        !needle ||
        row.item_name.toLocaleLowerCase().includes(needle) ||
        row.sku?.toLocaleLowerCase().includes(needle),
      )
      .sort((left, right) => left.item_name.localeCompare(right.item_name));
  }, [query, stock]);

  const loading = loadingWarehouses || loadingStock;

  return (
    <>
      <header className="inventory-header">
        <div>
          <h1>Inventory</h1>
          <p>Current stock and movement history.</p>
        </div>
        {!permissionsLoading && canImport && <Link className="inventory-adjust-button" href="/app/onboarding?source=inventory"><Upload aria-hidden="true" />Import inventory</Link>}
      </header>

      <div className="inventory-toolbar">
        <label className="inventory-search">
          <span className="sr-only">Search items or SKU</span>
          <Search aria-hidden="true" />
          <input
            type="search"
            placeholder="Search items or SKU"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="inventory-warehouse">
          <span className="sr-only">Warehouse</span>
          <select
            aria-label="Warehouse"
            value={warehouseId}
            disabled={loadingWarehouses || warehouses.length === 0}
            onChange={(event) => {
              const next = event.target.value;
              setWarehouseId(next);
              router.replace(`/app/inventory?warehouse_id=${encodeURIComponent(next)}`);
            }}
          >
            {warehouses.length === 0 && <option value="">No warehouses</option>}
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
            ))}
          </select>
        </label>
        {!permissionsLoading && canAdjust && warehouseId && (
          <details className="inventory-more">
            <summary>More <ChevronDown aria-hidden="true" /></summary>
            <div>
              <Link href={`/app/inventory/adjust?mode=opening&warehouse_id=${encodeURIComponent(warehouseId)}`}>Opening balance</Link>
              <Link href={`/app/inventory/adjust?warehouse_id=${encodeURIComponent(warehouseId)}`}>Manual adjustment</Link>
            </div>
          </details>
        )}
      </div>

      {!permissionsLoading && warehouseId && (canCount || canWriteOff || canTransfer) && (
        <nav className="inventory-primary-actions" aria-label="Inventory actions">
          {canCount && <Link href={`/app/inventory/counts/new?warehouse_id=${encodeURIComponent(warehouseId)}`}>Count stock</Link>}
          {canWriteOff && <Link href={`/app/inventory/write-offs/new?warehouse_id=${encodeURIComponent(warehouseId)}`}>Write off</Link>}
          {canTransfer && <Link href={`/app/inventory/transfers/new?source_warehouse_id=${encodeURIComponent(warehouseId)}`}>Transfer</Link>}
        </nav>
      )}

      {totalValue !== null && !loading && !error && (
        <section className="inventory-total-card" aria-label="Inventory valuation">
          <span>Total stock value</span>
          <strong>{formatInventoryMoney(totalValue, currentOrganization?.currency_code ?? "KZT")}</strong>
          <small>Selected warehouse</small>
        </section>
      )}

      {error ? (
        <div className="inventory-state is-error" role="alert">
          <strong>Inventory could not be loaded.</strong>
          <span>{error}</span>
        </div>
      ) : loading ? (
        <div className="inventory-state" aria-live="polite">Loading inventory…</div>
      ) : warehouses.length === 0 ? (
        <div className="inventory-state">
          <strong>No warehouse for this location</strong>
          <span>Create a warehouse before adding stock.</span>
        </div>
      ) : stock.length === 0 ? (
        <div className="inventory-state">
          <strong>No stock records yet</strong>
          <span>Post an opening balance or inventory adjustment to get started.</span>
          {!permissionsLoading && canAdjust && warehouseId && (
            <Link href={`/app/inventory/adjust?mode=opening&warehouse_id=${encodeURIComponent(warehouseId)}`}>
              Add opening balance
            </Link>
          )}
        </div>
      ) : filteredStock.length === 0 ? (
        <div className="inventory-state">
          <strong>No matching items</strong>
          <span>Try a different item name or SKU.</span>
        </div>
      ) : (
        <div className="inventory-table-wrap">
          <table className="inventory-table">
            <thead><tr><th>Item</th><th>Stock</th><th>Average cost</th><th>Value</th></tr></thead>
            <tbody>
              {filteredStock.map((row) => {
                const negative = isNegativeDecimal(row.quantity);
                const href = `/app/inventory/items/${row.inventory_item_id}?warehouse_id=${encodeURIComponent(warehouseId)}`;
                return (
                  <tr key={`${row.warehouse_id}:${row.inventory_item_id}`}>
                    <td>
                      <Link className="inventory-item-link" href={href}>{row.item_name}</Link>
                      {row.sku && <span>{row.sku}</span>}
                    </td>
                    <td className={negative ? "inventory-quantity is-negative" : "inventory-quantity"}>
                      {negative && <TriangleAlert aria-label="Negative stock" />}
                      {formatInventoryQuantity(row.quantity, row.base_unit)}
                    </td>
                    <td>
                      {row.average_unit_cost === null ? (
                        <span className="inventory-cost-hidden">Restricted</span>
                      ) : (
                        <span className={row.average_unit_cost === "0" ? "inventory-cost-warning" : ""}>
                          {formatUnitCost(
                            row.average_unit_cost,
                            row.base_unit,
                            currentOrganization?.currency_code ?? "KZT",
                            row.quantity,
                          )}
                        </span>
                      )}
                    </td>
                    <td>
                      <Link className="inventory-updated-link" href={href} aria-label={`Open ${row.item_name}`}>
                        <span>
                          {row.inventory_value === null
                            ? "Restricted"
                            : formatInventoryMoney(row.inventory_value, currentOrganization?.currency_code ?? "KZT")}
                        </span>
                        <ChevronRight aria-hidden="true" />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {!loading && !error && filteredStock.length > 0 && (
        <p className="inventory-count">{filteredStock.length} {filteredStock.length === 1 ? "item" : "items"}</p>
      )}
    </>
  );
}
