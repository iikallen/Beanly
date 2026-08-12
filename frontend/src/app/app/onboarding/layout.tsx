"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";

export default function SetupLayout({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const {
    loading: workspaceLoading,
    error,
    organizations,
    currentOrganization,
    currentLocation,
  } = useWorkspace();
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
      <AppSidebar active="onboarding" />
      <section className="setup-content">{children}</section>
    </main>
  );
}
