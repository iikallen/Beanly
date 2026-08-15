"use client";

import { MapPin } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";

export default function OnlineOrdersLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const workspace = useWorkspace();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, router, user]);

  if (loading || workspace.loading || !user) return <main className="loading-state">Loading…</main>;
  if (!workspace.currentOrganization || !workspace.currentLocation) return <main className="loading-state">Preparing workspace…</main>;

  return <main className="app-shell">
    <AppSidebar active="online-orders" />
    <div className="menu-workspace">
      <header className="menu-topbar">
        <label className="menu-topbar-location"><MapPin aria-hidden="true" /><span className="sr-only">Current location</span>
          <select value={workspace.currentLocation.id} onChange={(event) => workspace.selectLocation(event.target.value)}>
            {workspace.locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
          </select>
        </label>
        <div className="menu-topbar-user"><span aria-hidden="true">{user.first_name[0]}{user.last_name[0]}</span><strong>{user.first_name} {user.last_name}</strong></div>
      </header>
      <section className="menu-content">{children}</section>
    </div>
  </main>;
}
