"use client";

import { MapPin } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";

export default function PromotionsLayout({ children }: { children: React.ReactNode }) {
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

  return (
    <main className="app-shell">
      <AppSidebar active="promotions" />
      <div className="menu-workspace">
        <header className="menu-topbar">
          <label className="menu-topbar-location"><MapPin aria-hidden="true" /><span className="sr-only">Current location</span>
            <select value={workspace.currentLocation.id} onChange={(event) => workspace.selectLocation(event.target.value)}>
              {workspace.locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
            </select>
          </label>
          <div className="menu-topbar-user"><span aria-hidden="true">{user.first_name.charAt(0)}{user.last_name.charAt(0)}</span><strong>{user.first_name} {user.last_name}</strong></div>
        </header>
        <section className="menu-content">{children}</section>
      </div>
    </main>
  );
}
