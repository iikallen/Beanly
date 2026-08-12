"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useInventoryPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function loadPermissions() {
      await Promise.resolve();
      if (cancelled) return;
      setPermissions([]);
      setLoading(true);
      if (!accessToken || !currentOrganization) {
        setLoading(false);
        return;
      }
      try {
        const context = await api.getOrganizationContext(currentOrganization.id, accessToken);
        if (!cancelled) setPermissions(context.permissions);
      } catch {
        if (!cancelled) setPermissions([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadPermissions();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  return {
    loading,
    canRead: permissions.includes("inventory.read"),
    canAdjust: permissions.includes("inventory.adjust"),
    canWriteOff: permissions.includes("inventory.writeoff"),
    canCount: permissions.includes("inventory.count"),
    canTransfer: permissions.includes("inventory.transfer"),
    canReadMovements: permissions.includes("inventory.movement.read"),
    canImport: permissions.includes("menu.import"),
  };
}
