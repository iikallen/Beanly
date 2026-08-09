"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useMenuPermissions() {
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

  const legacyWrite = permissions.includes("menu.write");
  return {
    loading,
    canRead: permissions.includes("menu.read") || legacyWrite,
    canCreateProduct: legacyWrite || permissions.includes("menu.product.create"),
    canUpdateProduct: legacyWrite || permissions.includes("menu.product.update"),
    canArchiveProduct: legacyWrite || permissions.includes("menu.product.archive"),
    canReadRecipe: legacyWrite || permissions.includes("menu.recipe.read"),
    canWriteRecipe: legacyWrite || permissions.includes("menu.recipe.write"),
    canWritePrice: legacyWrite || permissions.includes("menu.price.write"),
    canWriteModifier: legacyWrite || permissions.includes("menu.modifier.write"),
  };
}
