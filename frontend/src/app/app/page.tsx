"use client";

import {
  ArrowDownUp,
  Banknote,
  Boxes,
  ClipboardCheck,
  ClipboardList,
  CircleAlert,
  Percent,
  ReceiptText,
  ShoppingBag,
  WalletCards,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { DashboardAlerts } from "@/components/dashboard/dashboard-alerts";
import { DashboardHeader } from "@/components/dashboard/dashboard-header";
import { DashboardKpi, DashboardMetricRail } from "@/components/dashboard/dashboard-kpi";
import { DashboardLocationScorecard } from "@/components/dashboard/dashboard-location-scorecard";
import { DashboardPaymentMix } from "@/components/dashboard/dashboard-payment-mix";
import { DashboardAccessState, DashboardError, DashboardLoading } from "@/components/dashboard/dashboard-state";
import { DashboardTrend } from "@/components/dashboard/dashboard-trend";
import { useWorkspace } from "@/components/workspace-provider";
import { useDashboardPermissions } from "@/hooks/use-dashboard-permissions";
import { api, type DashboardOverview, type DashboardPeriod } from "@/lib/api";
import {
  formatDashboardMinor,
  formatDashboardMoney,
  formatPercent,
  localDateInput,
} from "@/lib/dashboard";

export default function AppPage() {
  const { user, accessToken, loading: authLoading } = useAuth();
  const {
    loading: workspaceLoading,
    error: workspaceError,
    organizations,
    currentOrganization,
    currentLocation,
  } = useWorkspace();
  const permissions = useDashboardPermissions();
  const router = useRouter();
  const today = useMemo(() => localDateInput(), []);
  const [period, setPeriod] = useState<DashboardPeriod>("TODAY");
  const [allLocations, setAllLocations] = useState(false);
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(today);
  const [dashboardResult, setDashboardResult] = useState<{
    scopeKey: string;
    data: DashboardOverview;
  } | null>(null);
  const [loadingDashboard, setLoadingDashboard] = useState(true);
  const [errorResult, setErrorResult] = useState<{ scopeKey: string; message: string } | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestId = useRef(0);
  const dashboardScopeKey = [
    currentOrganization?.id ?? "",
    currentLocation?.id ?? "",
    allLocations ? "ALL" : "LOCATION",
    period,
    period === "CUSTOM" ? dateFrom : "",
    period === "CUSTOM" ? dateTo : "",
  ].join(":");
  const dashboard = dashboardResult?.scopeKey === dashboardScopeKey ? dashboardResult.data : null;
  const error = errorResult?.scopeKey === dashboardScopeKey ? errorResult.message : "";

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
    if (!authLoading && user && !workspaceLoading && !workspaceError && organizations.length === 0) {
      router.replace("/onboarding");
    }
    if (!permissions.loading && permissions.redirectToPos) router.replace("/app/pos");
  }, [authLoading, organizations.length, permissions.loading, permissions.redirectToPos, router, user, workspaceError, workspaceLoading]);

  useEffect(() => {
    let cancelled = false;
    const activeRequestId = ++requestId.current;
    async function loadDashboard() {
      await Promise.resolve();
      if (
        cancelled ||
        !accessToken ||
        !currentOrganization ||
        !currentLocation ||
        permissions.loading ||
        !permissions.canRead ||
        permissions.redirectToPos ||
        (period === "CUSTOM" && (!dateFrom || !dateTo))
      ) return;

      setLoadingDashboard(true);
      setErrorResult(null);
      try {
        const next = await api.getDashboardOverview(currentOrganization.id, accessToken, {
          period,
          locationId: allLocations ? undefined : currentLocation.id,
          dateFrom: period === "CUSTOM" ? dateFrom : undefined,
          dateTo: period === "CUSTOM" ? dateTo : undefined,
        });
        if (!cancelled && requestId.current === activeRequestId) {
          setDashboardResult({ scopeKey: dashboardScopeKey, data: next });
        }
      } catch (caught) {
        if (!cancelled && requestId.current === activeRequestId) {
          setErrorResult({
            scopeKey: dashboardScopeKey,
            message: caught instanceof Error ? caught.message : "Unable to load dashboard",
          });
        }
      } finally {
        if (!cancelled && requestId.current === activeRequestId) setLoadingDashboard(false);
      }
    }
    void loadDashboard();
    return () => {
      cancelled = true;
    };
  }, [accessToken, allLocations, currentLocation, currentOrganization, dashboardScopeKey, dateFrom, dateTo, period, permissions.canRead, permissions.loading, permissions.redirectToPos, refreshKey]);

  if (authLoading || workspaceLoading || permissions.loading || !user || permissions.redirectToPos) {
    return <main className="loading-state">Loading…</main>;
  }
  if (workspaceError) return <main className="loading-state error-state">{workspaceError}</main>;
  if (!currentOrganization || !currentLocation) {
    return <main className="loading-state">Preparing workspace…</main>;
  }

  const finance = permissions.canReadFinance ? dashboard?.finance : null;
  const currency = finance?.currency_code ?? currentOrganization.currency_code;
  const hasRefundBreakdown = dashboard?.sales.gross_sales_minor !== undefined
    && dashboard.sales.refund_amount_minor !== undefined
    && dashboard.sales.net_sales_minor !== undefined;
  const mainMetrics = dashboard ? [
    {
      label: hasRefundBreakdown ? "Net Sales" : "Revenue",
      value: hasRefundBreakdown
        ? formatDashboardMinor(dashboard.sales.net_sales_minor!, currency)
        : formatDashboardMoney(dashboard.sales.revenue.current, currency),
      metric: dashboard.sales.revenue,
      icon: <Banknote />,
      breakdown: hasRefundBreakdown
        ? `Gross ${formatDashboardMinor(dashboard.sales.gross_sales_minor!, currency)} · Refunds −${formatDashboardMinor(dashboard.sales.refund_amount_minor!, currency)}`
        : undefined,
    },
    {
      label: "Orders",
      value: new Intl.NumberFormat().format(dashboard.sales.paid_orders.current),
      metric: dashboard.sales.paid_orders,
      icon: <ShoppingBag />,
    },
    {
      label: "Average check",
      value: formatDashboardMoney(dashboard.sales.average_check.current, currency),
      metric: dashboard.sales.average_check,
      icon: <ReceiptText />,
    },
  ] : [];

  return (
    <main className="app-shell">
      <AppSidebar active="dashboard" />
      <section className="dashboard-content dashboard-workspace">
        <DashboardHeader
          currentLocationId={currentLocation.id}
          currentLocationName={currentLocation.name}
          locationId={allLocations ? "" : currentLocation.id}
          period={period}
          dateFrom={dateFrom}
          dateTo={dateTo}
          scope={dashboard?.scope ?? null}
          refreshing={loadingDashboard && dashboard !== null}
          onLocationChange={(value) => setAllLocations(value === "")}
          onPeriodChange={setPeriod}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
          onRefresh={() => setRefreshKey((current) => current + 1)}
        />

        {!permissions.canRead ? (
          <DashboardAccessState />
        ) : error ? (
          <DashboardError message={error} onRetry={() => setRefreshKey((current) => current + 1)} />
        ) : !dashboard ? (
          <DashboardLoading />
        ) : dashboard ? (
          <>
            <section className="dashboard-kpi-grid" aria-label="Key performance indicators">
              {mainMetrics.map((metric) => <DashboardKpi key={metric.label} {...metric} />)}
              {finance ? (
                <DashboardKpi
                  label="Operating Profit"
                  value={formatDashboardMoney(finance.operating_profit, currency)}
                  metric={finance.operating_profit_comparison}
                  icon={<WalletCards />}
                />
              ) : (
                <DashboardKpi
                  label="Open orders"
                  value={new Intl.NumberFormat().format(dashboard.sales.open_orders)}
                  detail={`${dashboard.sales.open_shifts} open shifts`}
                  icon={<ClipboardList />}
                />
              )}
            </section>
            {finance && finance.incomplete_cogs_sales > 0 && <div className="finance-quality-warning" role="status"><CircleAlert aria-hidden="true" /><div><strong>Estimated or incomplete COGS</strong><p>{new Intl.NumberFormat().format(finance.incomplete_cogs_sales)} sales need recipe or cost review. Revenue and refund totals remain available.</p></div></div>}

            <DashboardMetricRail metrics={finance ? [
              { label: "Gross Margin", value: formatPercent(finance.gross_margin_percent), icon: <Percent /> },
              { label: "Inventory Loss", value: formatDashboardMoney(finance.inventory_losses, currency), icon: <ArrowDownUp /> },
              { label: "Inventory Value", value: formatDashboardMoney(dashboard.inventory.total_value, currency), icon: <Boxes /> },
              { label: "Net Cash Movement", value: formatDashboardMinor(finance.net_cash_movement_minor, currency), icon: <WalletCards /> },
            ] : [
              { label: "Inventory Value", value: formatDashboardMoney(dashboard.inventory.total_value, currency), icon: <Boxes /> },
              { label: "Negative Stock", value: new Intl.NumberFormat().format(dashboard.inventory.negative_stock_count), icon: <ArrowDownUp /> },
              { label: "Inventory Counts", value: new Intl.NumberFormat().format(dashboard.inventory.active_count_count), icon: <ClipboardCheck /> },
            ]} />

            <div className="dashboard-insights-grid">
              <DashboardTrend
                points={dashboard.trend}
                currency={currency}
                period={dashboard.scope.period}
                timezone={dashboard.scope.timezone}
                emptyActions={{
                  canCreateSales: permissions.canCreateSales,
                  canAdjustInventory: permissions.canAdjustInventory,
                  canCreateMenuProduct: permissions.canCreateMenuProduct,
                }}
              />
              <DashboardPaymentMix items={dashboard.payment_mix} currency={currency} />
            </div>
            <div className="dashboard-bottom-grid">
              <DashboardAlerts alerts={dashboard.alerts} />
              <DashboardLocationScorecard locations={dashboard.locations} currency={currency} />
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}
