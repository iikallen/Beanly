"use client";

import { ArrowLeft, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { ApiError, api, type MovementRow, type StockRow, type WarehouseResponse } from "@/lib/api";
import {
  formatInventoryDate,
  formatInventoryMoney,
  formatInventoryQuantity,
  formatTransactionType,
  formatUnitCost,
  isNegativeDecimal,
} from "@/lib/inventory";

export default function InventoryItemPage() {
  const { itemId } = useParams<{ itemId: string }>();
  const searchParams = useSearchParams();
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canAdjust, loading: permissionsLoading } = useInventoryPermissions();
  const [warehouse, setWarehouse] = useState<WarehouseResponse | null>(null);
  const [stock, setStock] = useState<StockRow | null>(null);
  const [movements, setMovements] = useState<MovementRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [historyRestricted, setHistoryRestricted] = useState(false);
  const [requestedWarehouse] = useState(() => searchParams.get("warehouse_id"));

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [];
      setLoading(true);
      setError("");
      return api.listInventoryWarehouses(currentOrganization.id, accessToken);
    })
      .then(async (available) => {
        const local = available.filter(
          (item) => item.is_active && item.location_id === currentLocation.id,
        );
        const selected =
          local.find((item) => item.id === requestedWarehouse) ?? local[0] ?? null;
        if (!selected) throw new Error("No warehouse is available for this location.");
        const nextStock = await api.getItemStock(
          itemId,
          selected.id,
          currentOrganization.id,
          accessToken,
        );
        let nextMovements: MovementRow[] = [];
        let restricted = false;
        try {
          nextMovements = await api.listItemMovements(
            itemId,
            selected.id,
            currentOrganization.id,
            accessToken,
          );
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 403) throw caught;
          restricted = true;
        }
        if (cancelled) return;
        setWarehouse(selected);
        setStock(nextStock);
        setMovements(nextMovements);
        setHistoryRestricted(restricted);
      })
      .catch((caught) => {
        if (!cancelled) {
          setStock(null);
          setMovements([]);
          setError(caught instanceof Error ? caught.message : "Unable to load item stock");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, itemId, requestedWarehouse]);

  const orderedMovements = useMemo(
    () => [...movements].sort((left, right) =>
      (right.posted_at ?? right.created_at).localeCompare(left.posted_at ?? left.created_at),
    ),
    [movements],
  );

  if (loading) return <div className="inventory-state">Loading item history…</div>;
  if (error || !stock || !warehouse) {
    return (
      <div className="inventory-state is-error" role="alert">
        <strong>Item stock could not be loaded.</strong>
        <span>{error || "Stock record not found."}</span>
        <Link href="/app/inventory">Back to inventory</Link>
      </div>
    );
  }

  const negative = isNegativeDecimal(stock.quantity);
  const inventoryHref = `/app/inventory?warehouse_id=${encodeURIComponent(warehouse.id)}`;

  return (
    <>
      <Link className="inventory-back-link" href={inventoryHref}>
        <ArrowLeft aria-hidden="true" />
        Inventory
      </Link>
      <header className="inventory-header inventory-item-header">
        <div>
          <p className="eyebrow">{stock.sku ?? "Inventory item"}</p>
          <h1>{stock.item_name}</h1>
          <p>{warehouse.name}</p>
        </div>
        {!permissionsLoading && canAdjust && (
          <Link
            className="inventory-adjust-button"
            href={`/app/inventory/adjust?warehouse_id=${encodeURIComponent(warehouse.id)}&item_id=${encodeURIComponent(itemId)}`}
          >
            Adjust inventory
          </Link>
        )}
      </header>

      <section className={negative ? "stock-summary is-negative" : "stock-summary"}>
        <div>
          <span>Current stock</span>
          <strong>
            {negative && <TriangleAlert aria-label="Negative stock" />}
            {formatInventoryQuantity(stock.quantity, stock.base_unit)}
          </strong>
        </div>
        <div>
          <span>Average cost</span>
          <strong>
            {formatUnitCost(
              stock.average_unit_cost,
              stock.base_unit,
              currentOrganization?.currency_code ?? "KZT",
              stock.quantity,
            )}
          </strong>
        </div>
        <div>
          <span>Inventory value</span>
          <strong>
            {formatInventoryMoney(
              stock.inventory_value,
              currentOrganization?.currency_code ?? "KZT",
            )}
          </strong>
        </div>
        <small>Updated {formatInventoryDate(stock.updated_at)}</small>
      </section>

      <section className="movement-section">
        <div className="movement-heading">
          <div>
            <h2>Movement history</h2>
            <p>Every posted change to this item.</p>
          </div>
          <span>{orderedMovements.length} {orderedMovements.length === 1 ? "movement" : "movements"}</span>
        </div>
        {historyRestricted ? (
          <div className="inventory-state">
            <strong>Cost history is restricted</strong>
            <span>Your role can see current quantities but not financial movement costs.</span>
          </div>
        ) : orderedMovements.length === 0 ? (
          <div className="inventory-state">
            <strong>No movements yet</strong>
            <span>This item has no posted stock history in the selected warehouse.</span>
          </div>
        ) : (
          <div className="inventory-table-wrap movement-table-wrap">
            <table className="inventory-table movement-table">
              <thead>
                <tr>
                  <th>Movement</th><th>Change at cost</th><th>Stock after</th>
                  <th>Average after</th><th>Date</th>
                </tr>
              </thead>
              <tbody>
                {orderedMovements.map((movement) => {
                  const movementNegative = isNegativeDecimal(movement.quantity_delta);
                  return (
                    <tr key={movement.transaction_id}>
                      <td>
                        <strong>{formatTransactionType(movement.type)}</strong>
                        <span>
                          {movement.reference_type
                            ? `${formatTransactionType(movement.reference_type)} · ${movement.reference_id?.slice(0, 8)}`
                            : movement.note ?? movement.status}
                        </span>
                      </td>
                      <td className={movementNegative ? "inventory-quantity is-negative" : "inventory-quantity is-positive"}>
                        {formatInventoryQuantity(
                          movement.quantity_delta,
                          stock.base_unit,
                          true,
                        )}
                        <small>
                          @ {formatUnitCost(
                            movement.unit_cost_amount,
                            stock.base_unit,
                            currentOrganization?.currency_code ?? "KZT",
                            movement.quantity_delta,
                          )}
                        </small>
                      </td>
                      <td>{movement.quantity_after === null ? "—" : formatInventoryQuantity(movement.quantity_after, stock.base_unit)}</td>
                      <td>
                        {formatUnitCost(
                          movement.average_unit_cost_after,
                          stock.base_unit,
                          currentOrganization?.currency_code ?? "KZT",
                          movement.quantity_after,
                        )}
                      </td>
                      <td>{formatInventoryDate(movement.posted_at ?? movement.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
