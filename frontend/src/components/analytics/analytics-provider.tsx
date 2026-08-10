"use client";

import { createContext, useContext, useMemo, useState } from "react";

import { useWorkspace } from "@/components/workspace-provider";
import { useDashboardPermissions } from "@/hooks/use-dashboard-permissions";
import { analyticsDateRange } from "@/lib/analytics";

type AnalyticsContextValue = {
  canRead: boolean;
  canReadFinance: boolean;
  permissionsLoading: boolean;
  redirectToPos: boolean;
  dateFrom: string;
  dateTo: string;
  locationId: string;
  currency: string;
  setDateFrom: (value: string) => void;
  setDateTo: (value: string) => void;
  setLocationId: (value: string) => void;
};

const AnalyticsContext = createContext<AnalyticsContextValue | null>(null);

export function AnalyticsProvider({ children }: { children: React.ReactNode }) {
  const { currentOrganization, currentLocation } = useWorkspace();
  const initial = useMemo(() => analyticsDateRange(currentLocation?.timezone), [currentLocation?.timezone]);
  const permissions = useDashboardPermissions();
  const [dateFrom, setDateFrom] = useState(initial.dateFrom);
  const [dateTo, setDateTo] = useState(initial.dateTo);
  const [locationSelection, setLocationSelection] = useState({ organizationId: "", value: "" });
  const organizationId = currentOrganization?.id ?? "";
  const locationId = locationSelection.organizationId === organizationId ? locationSelection.value : "";

  return (
    <AnalyticsContext.Provider value={{
      canRead: permissions.canRead,
      canReadFinance: permissions.canReadFinance,
      permissionsLoading: permissions.loading,
      redirectToPos: permissions.redirectToPos,
      dateFrom,
      dateTo,
      locationId,
      currency: currentOrganization?.currency_code ?? "KZT",
      setDateFrom,
      setDateTo,
      setLocationId: (value) => setLocationSelection({ organizationId, value }),
    }}>
      {children}
    </AnalyticsContext.Provider>
  );
}

export function useAnalyticsScope() {
  const context = useContext(AnalyticsContext);
  if (!context) throw new Error("useAnalyticsScope must be used inside AnalyticsProvider");
  return context;
}
