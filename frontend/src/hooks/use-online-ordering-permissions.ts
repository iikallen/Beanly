"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useOnlineOrderingPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization) {
      queueMicrotask(() => { if (!cancelled) { setPermissions([]); setLoading(false); } });
      return;
    }
    queueMicrotask(() => { if (!cancelled) { setPermissions([]); setLoading(true); } });
    void api.getOrganizationContext(currentOrganization.id, accessToken)
      .then((value) => { if (!cancelled) setPermissions(value.permissions); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  return {
    loading,
    canRead: permissions.includes("online_orders.read"),
    canManage: permissions.includes("online_orders.manage"),
    canConfigure: permissions.includes("online_ordering.manage"),
  };
}
