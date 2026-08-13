"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function usePromotionPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      if (!accessToken || !currentOrganization) return setLoading(false);
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
    canRead: permissions.includes("promotions.read") || permissions.includes("promotions.write"),
    canWrite: permissions.includes("promotions.write"),
    canApply: permissions.includes("discounts.apply"),
    canOverride: permissions.includes("discounts.override"),
  };
}
