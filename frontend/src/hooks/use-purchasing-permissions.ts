"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function usePurchasingPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return null;
      setPermissions([]);
      setLoading(true);
      if (!accessToken || !currentOrganization) return null;
      return api.getTeam(currentOrganization.id, accessToken);
    })
      .then((team) => {
        if (!cancelled && team) setPermissions(team.permissions);
      })
      .catch(() => {
        if (!cancelled) setPermissions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  return {
    loading,
    canRead: permissions.includes("purchasing.read"),
    canCreate: permissions.includes("purchasing.create"),
    canUpdate: permissions.includes("purchasing.update"),
    canReceive: permissions.includes("purchasing.receive"),
    canCancel: permissions.includes("purchasing.cancel"),
  };
}
