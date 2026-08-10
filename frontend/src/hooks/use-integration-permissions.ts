"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { api } from "@/lib/api";

export function useIntegrationPermissions() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const [state, setState] = useState<{
    organizationId: string | null;
    permissions: string[];
    loading: boolean;
  }>({ organizationId: null, permissions: [], loading: true });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      await Promise.resolve();
      if (cancelled) return;
      if (!accessToken || !currentOrganization) {
        setState({ organizationId: null, permissions: [], loading: false });
        return;
      }
      setState({ organizationId: currentOrganization.id, permissions: [], loading: true });
      try {
        const context = await api.getOrganizationContext(currentOrganization.id, accessToken);
        if (!cancelled) setState({
          organizationId: currentOrganization.id,
          permissions: context.permissions,
          loading: false,
        });
      } catch {
        if (!cancelled) setState({
          organizationId: currentOrganization.id,
          permissions: [],
          loading: false,
        });
      }
    }

    void load();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  if (!currentOrganization || state.organizationId !== currentOrganization.id) {
    return { loading: true, canRead: false, canWrite: false };
  }
  return {
    loading: state.loading,
    canRead: state.permissions.includes("integrations.read"),
    canWrite: state.permissions.includes("integrations.write"),
  };
}
