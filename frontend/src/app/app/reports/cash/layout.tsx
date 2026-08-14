"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";

export default function CashReportsLayout({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const workspace = useWorkspace();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
    if (!authLoading && user && !workspace.loading && !workspace.error && workspace.organizations.length === 0) router.replace("/onboarding");
  }, [authLoading, router, user, workspace.error, workspace.loading, workspace.organizations.length]);

  if (authLoading || workspace.loading || !user) return <main className="loading-state">Loading…</main>;
  if (workspace.error) return <main className="loading-state error-state">{workspace.error}</main>;
  if (!workspace.currentOrganization || !workspace.currentLocation) return <main className="loading-state">Preparing workspace…</main>;
  return <main className="app-shell"><AppSidebar active="cash" /><section className="cash-report-content">{children}</section></main>;
}
