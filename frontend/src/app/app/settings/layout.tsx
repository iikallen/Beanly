"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useIntegrationPermissions } from "@/hooks/use-integration-permissions";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const {
    loading: workspaceLoading,
    error,
    organizations,
    currentOrganization,
    currentLocation,
  } = useWorkspace();
  const integrations = useIntegrationPermissions();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
    if (!authLoading && user && !workspaceLoading && !error && organizations.length === 0) {
      router.replace("/onboarding");
    }
  }, [authLoading, error, organizations.length, router, user, workspaceLoading]);

  if (authLoading || workspaceLoading || !user) {
    return <main className="loading-state">Loading…</main>;
  }
  if (error) return <main className="loading-state error-state">{error}</main>;
  if (!currentOrganization || !currentLocation) {
    return <main className="loading-state">Preparing workspace…</main>;
  }

  return (
    <main className="app-shell">
      <AppSidebar
        active="settings"
        settingsCanReadIntegrations={!integrations.loading && integrations.canRead}
      />
      <section className="settings-content">{children}</section>
    </main>
  );
}
