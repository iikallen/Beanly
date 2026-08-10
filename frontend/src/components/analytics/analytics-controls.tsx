"use client";

import { Clock3 } from "lucide-react";

import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { formatAnalyticsDateTime } from "@/lib/analytics";

export function AnalyticsHeader({
  title,
  description,
  dataAsOf,
  showLocation = true,
  children,
}: {
  title: string;
  description: string;
  dataAsOf?: string | null;
  showLocation?: boolean;
  children?: React.ReactNode;
}) {
  const { locations } = useWorkspace();
  const { dateFrom, dateTo, locationId, setDateFrom, setDateTo, setLocationId } = useAnalyticsScope();
  return (
    <header className="analytics-header">
      <div className="analytics-heading">
        <span className="analytics-eyebrow">Historical analytics</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="analytics-control-stack">
        <div className="analytics-controls">
          <label><span>From</span><input type="date" value={dateFrom} max={dateTo} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label><span>To</span><input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} /></label>
          {showLocation && <label><span>Location</span><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">All locations</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>}
          {children}
        </div>
        {dataAsOf !== undefined && <p className="analytics-freshness"><Clock3 aria-hidden="true" /> Data as of {formatAnalyticsDateTime(dataAsOf)}</p>}
      </div>
    </header>
  );
}
