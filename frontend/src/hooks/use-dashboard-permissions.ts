"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api, type MembershipRole } from "@/lib/api";

type DashboardAccess = {
  loading: boolean;
  canRead: boolean;
  canReadFinance: boolean;
  canCreateSales: boolean;
  canAdjustInventory: boolean;
  canCreateMenuProduct: boolean;
  redirectToPos: boolean;
  role: MembershipRole | null;
};

type DashboardAccessResult = DashboardAccess & { organizationId: string | null };

const EMPTY_ACCESS: DashboardAccess = {
  loading: true,
  canRead: false,
  canReadFinance: false,
  canCreateSales: false,
  canAdjustInventory: false,
  canCreateMenuProduct: false,
  redirectToPos: false,
  role: null,
};

export function useDashboardPermissions(): DashboardAccess {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [state, setState] = useState<DashboardAccessResult>({
    ...EMPTY_ACCESS,
    organizationId: null,
  });

  useEffect(() => {
    let cancelled = false;

    async function loadPermissions() {
      await Promise.resolve();
      if (cancelled) return;
      if (!accessToken || !currentOrganization) {
        setState({
          loading: false,
          canRead: false,
          canReadFinance: false,
          canCreateSales: false,
          canAdjustInventory: false,
          canCreateMenuProduct: false,
          redirectToPos: false,
          role: null,
          organizationId: null,
        });
        return;
      }

      setState({ ...EMPTY_ACCESS, organizationId: currentOrganization.id });
      try {
        const context = await api.getOrganizationContext(
          currentOrganization.id,
          accessToken,
        );
        if (cancelled) return;
        setState({
          loading: false,
          canRead: context.permissions.includes("analytics.read"),
          canReadFinance: context.permissions.includes("finance.read"),
          canCreateSales: context.permissions.includes("sales.create"),
          canAdjustInventory: context.permissions.includes("inventory.adjust"),
          canCreateMenuProduct: context.permissions.includes("menu.product.create"),
          redirectToPos: context.role === "CASHIER" || context.role === "BARISTA",
          role: context.role,
          organizationId: currentOrganization.id,
        });
      } catch {
        if (!cancelled) {
          setState({
            loading: false,
            canRead: false,
            canReadFinance: false,
            canCreateSales: false,
            canAdjustInventory: false,
            canCreateMenuProduct: false,
            redirectToPos: false,
            role: null,
            organizationId: currentOrganization.id,
          });
        }
      }
    }

    void loadPermissions();
    return () => {
      cancelled = true;
    };
  }, [accessToken, currentOrganization]);

  if (!currentOrganization || state.organizationId !== currentOrganization.id) {
    return EMPTY_ACCESS;
  }
  return state;
}
