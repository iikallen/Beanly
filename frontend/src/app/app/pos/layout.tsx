"use client";

import { MapPin } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { readCurrentSession } from "@/lib/offline/db";
import type { OfflineSession } from "@/lib/offline/types";

export default function PosLayout({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const {
    loading: workspaceLoading,
    error,
    organizations,
    currentOrganization,
    currentLocation,
    locations,
    selectLocation,
  } = useWorkspace();
  const router = useRouter();
  const [cachedSession, setCachedSession] = useState<OfflineSession | null>(null);
  const [cacheChecked, setCacheChecked] = useState(false);

  useEffect(() => {
    if (authLoading) return;
    if (user && !error) return;
    let cancelled = false;
    readCurrentSession()
      .then((session) => {
        if (cancelled) return;
        const usable = session && (session.status === "ACTIVE" || session.status === "EXPIRED") && session.device_id;
        setCachedSession(usable ? session : null);
        if (!usable && !user) router.replace("/login");
      })
      .finally(() => { if (!cancelled) setCacheChecked(true); });
    return () => { cancelled = true; };
  }, [authLoading, error, router, user]);

  useEffect(() => {
    if (!authLoading && user && !workspaceLoading && !error && organizations.length === 0) router.replace("/onboarding");
  }, [authLoading, error, organizations.length, router, user, workspaceLoading]);

  if (authLoading || ((!user || Boolean(error)) && !cacheChecked) || (user && workspaceLoading)) {
    return <main className="loading-state">Loading…</main>;
  }
  if ((!user || error) && cachedSession) {
    return (
      <main className="pos-offline-shell">
        <div className="pos-workspace">
          <header className="menu-topbar">
            <strong>{cachedSession.shell.location_name} · {cachedSession.shell.register_name}</strong>
            <span>Offline session · {cachedSession.shell.operator_name}</span>
          </header>
          {children}
        </div>
      </main>
    );
  }
  if (error) return <main className="loading-state error-state">{error}</main>;
  if (!user) return <main className="loading-state">Loading…</main>;
  if (!currentOrganization || !currentLocation) {
    return <main className="loading-state">Preparing workspace…</main>;
  }

  return (
    <main className="app-shell">
      <AppSidebar active="pos" />
      <div className="pos-workspace">
        <header className="menu-topbar">
          <label className="menu-topbar-location">
            <MapPin aria-hidden="true" />
            <span className="sr-only">Current location</span>
            <select
              value={currentLocation.id}
              onChange={(event) => selectLocation(event.target.value)}
            >
              {locations.filter((location) => location.is_active).map((location) => (
                <option key={location.id} value={location.id}>{location.name}</option>
              ))}
            </select>
          </label>
          <div className="menu-topbar-user">
            <span aria-hidden="true">
              {user.first_name.charAt(0)}{user.last_name.charAt(0)}
            </span>
            <strong>{user.first_name} {user.last_name}</strong>
          </div>
        </header>
        {children}
      </div>
    </main>
  );
}
