"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AnalyticsProvider, useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const { loading: workspaceLoading, error, organizations, currentOrganization, currentLocation } = useWorkspace();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
    if (!authLoading && user && !workspaceLoading && !error && organizations.length === 0) router.replace("/onboarding");
  }, [authLoading, error, organizations.length, router, user, workspaceLoading]);

  if (authLoading || workspaceLoading || !user) return <main className="loading-state">Loading…</main>;
  if (error) return <main className="loading-state error-state">{error}</main>;
  if (!currentOrganization || !currentLocation) return <main className="loading-state">Preparing workspace…</main>;

  return <AnalyticsProvider><AnalyticsFrame>{children}</AnalyticsFrame></AnalyticsProvider>;
}

function AnalyticsFrame({ children }: { children: React.ReactNode }) {
  const { permissionsLoading, redirectToPos } = useAnalyticsScope();
  const router = useRouter();
  useEffect(() => { if (!permissionsLoading && redirectToPos) router.replace("/app/pos"); }, [permissionsLoading, redirectToPos, router]);
  if (permissionsLoading || redirectToPos) return <main className="loading-state">Loading…</main>;
  return <main className="app-shell"><AppSidebar active="analytics" /><section className="analytics-content">{children}</section></main>;
}
