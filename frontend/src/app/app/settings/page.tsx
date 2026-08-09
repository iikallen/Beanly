"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";

export default function SettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const { loading, error, organizations, currentOrganization, currentLocation } =
    useWorkspace();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
    if (!authLoading && user && !loading && !error && organizations.length === 0) {
      router.replace("/onboarding");
    }
  }, [authLoading, error, loading, organizations.length, router, user]);

  if (authLoading || loading || !user) {
    return <main className="loading-state">Loading…</main>;
  }
  if (error) return <main className="loading-state error-state">{error}</main>;
  if (!currentOrganization || !currentLocation) {
    return <main className="loading-state">Preparing workspace…</main>;
  }

  return (
    <main className="app-shell">
      <AppSidebar active="settings" />
      <section className="dashboard-content">
        <h1>Settings</h1>
        <p>Organization settings will be added in a later stage.</p>
      </section>
    </main>
  );
}
