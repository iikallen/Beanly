import { AlertCircle, ArrowRight, Coffee, PackagePlus } from "lucide-react";
import Link from "next/link";

export function DashboardLoading() {
  return (
    <div className="dashboard-loading" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading dashboard…</span>
      <div className="dashboard-loading-heading" />
      <div className="dashboard-loading-grid">
        {Array.from({ length: 4 }, (_, index) => <div key={index} />)}
      </div>
      <div className="dashboard-loading-panel" />
    </div>
  );
}

export function DashboardError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="dashboard-state is-error" role="alert">
      <AlertCircle aria-hidden="true" />
      <strong>Dashboard could not be loaded.</strong>
      <span>{message}</span>
      <button type="button" onClick={onRetry}>Try again</button>
    </div>
  );
}

export function DashboardAccessState() {
  return (
    <div className="dashboard-state">
      <AlertCircle aria-hidden="true" />
      <strong>Dashboard access required</strong>
      <span>Your role cannot view business analytics.</span>
    </div>
  );
}

export type DashboardEmptyActions = {
  canCreateSales: boolean;
  canAdjustInventory: boolean;
  canCreateMenuProduct: boolean;
};

export function DashboardEmpty({ actions }: { actions: DashboardEmptyActions }) {
  const hasActions = actions.canCreateSales || actions.canAdjustInventory || actions.canCreateMenuProduct;
  return (
    <div className="dashboard-empty">
      <Coffee aria-hidden="true" />
      <strong>No completed sales in this period yet.</strong>
      {hasActions && (
        <div>
          {actions.canCreateSales && <Link href="/app/pos">Open POS <ArrowRight aria-hidden="true" /></Link>}
          {actions.canAdjustInventory && <Link href="/app/inventory/adjust"><PackagePlus aria-hidden="true" /> Set opening inventory</Link>}
          {actions.canCreateMenuProduct && <Link href="/app/menu/products/new">Create menu <ArrowRight aria-hidden="true" /></Link>}
        </div>
      )}
    </div>
  );
}
