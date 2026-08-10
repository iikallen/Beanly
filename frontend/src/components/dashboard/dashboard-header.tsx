import { CalendarDays, RefreshCw } from "lucide-react";

import type { DashboardOverview, DashboardPeriod } from "@/lib/api";
import { DASHBOARD_PERIODS, formatScopeDate } from "@/lib/dashboard";

export function DashboardHeader({
  currentLocationId,
  currentLocationName,
  locationId,
  period,
  dateFrom,
  dateTo,
  scope,
  refreshing,
  onLocationChange,
  onPeriodChange,
  onDateFromChange,
  onDateToChange,
  onRefresh,
}: {
  currentLocationId: string;
  currentLocationName: string;
  locationId: string;
  period: DashboardPeriod;
  dateFrom: string;
  dateTo: string;
  scope: DashboardOverview["scope"] | null;
  refreshing: boolean;
  onLocationChange: (value: string) => void;
  onPeriodChange: (value: DashboardPeriod) => void;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  onRefresh: () => void;
}) {
  return (
    <header className="dashboard-header">
      <div className="dashboard-title-block">
        <h1>Dashboard</h1>
        <p>{scope?.location_name ?? (locationId ? currentLocationName : "All locations")}</p>
      </div>
      <div className="dashboard-controls">
        <label>
          <span>Location</span>
          <select value={locationId} onChange={(event) => onLocationChange(event.target.value)}>
            <option value={currentLocationId}>{currentLocationName}</option>
            <option value="">All locations</option>
          </select>
        </label>
        <label>
          <span>Period</span>
          <select
            value={period}
            onChange={(event) => onPeriodChange(event.target.value as DashboardPeriod)}
          >
            {DASHBOARD_PERIODS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        {period === "CUSTOM" && (
          <div className="dashboard-custom-dates">
            <label>
              <span>From</span>
              <input type="date" value={dateFrom} max={dateTo} onChange={(event) => onDateFromChange(event.target.value)} />
            </label>
            <label>
              <span>To</span>
              <input type="date" value={dateTo} min={dateFrom} onChange={(event) => onDateToChange(event.target.value)} />
            </label>
          </div>
        )}
        <div className="dashboard-updated" aria-live="polite">
          <CalendarDays aria-hidden="true" />
          <span>{scope ? formatScopeDate(scope) : "Reporting period"}</span>
          <small>{scope ? "Updated just now" : ""}</small>
        </div>
        <button className="dashboard-refresh" type="button" onClick={onRefresh} disabled={refreshing}>
          <RefreshCw className={refreshing ? "is-spinning" : ""} aria-hidden="true" />
          {refreshing ? "Refreshing" : "Refresh"}
        </button>
      </div>
    </header>
  );
}
