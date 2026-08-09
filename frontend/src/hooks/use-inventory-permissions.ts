"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useInventoryPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [canAdjust, setCanAdjust] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function loadPermissions() {
      await Promise.resolve();
      if (cancelled) return;
      setCanAdjust(false);
      setLoading(true);
      if (!accessToken || !currentOrganization) {
        setLoading(false);
        return;
      }
      try {
        const team = await api.getTeam(currentOrganization.id, accessToken);
        if (!cancelled) setCanAdjust(team.permissions.includes("inventory.adjust"));
      } catch {
        if (!cancelled) setCanAdjust(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadPermissions();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  return { canAdjust, loading };
}
