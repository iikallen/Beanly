"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useKitchenPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
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
    void load();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  return {
    loading,
    canRead: permissions.includes("kitchen.read"),
    canWork: permissions.includes("kitchen.work"),
    canExpo: permissions.includes("kitchen.expo"),
    canManage: permissions.includes("kitchen.manage"),
    canReport: permissions.includes("kitchen.report"),
  };
}
