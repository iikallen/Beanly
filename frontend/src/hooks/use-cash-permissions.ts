"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useCashPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled) return;
      setLoading(true);
      if (!accessToken || !currentOrganization) { setPermissions([]); setLoading(false); return; }
      try { const context = await api.getOrganizationContext(currentOrganization.id, accessToken); if (!cancelled) setPermissions(context.permissions); }
      catch { setPermissions([]); }
      finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  return {
    loading,
    canReport: permissions.includes("cash.drawer.report"),
    canViewExpected: permissions.includes("cash.drawer.view_expected"),
  };
}
