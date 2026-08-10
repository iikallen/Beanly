"use client";

import { PlugZap } from "lucide-react";
import Link from "next/link";

import { useIntegrationPermissions } from "@/hooks/use-integration-permissions";

export default function SettingsPage() {
  const integrations = useIntegrationPermissions();

  return (
    <>
      <header className="settings-header">
        <h1>Settings</h1>
        <p>Manage organization-level configuration and connected services.</p>
      </header>

      <div className="settings-card-grid">
        {!integrations.loading && integrations.canRead && (
          <Link className="settings-entry-card" href="/app/settings/integrations">
            <span className="settings-entry-icon" aria-hidden="true"><PlugZap /></span>
            <span><strong>Integrations</strong><small>Providers, locations and delivery activity</small></span>
            <span aria-hidden="true">→</span>
          </Link>
        )}
        {!integrations.loading && !integrations.canRead && (
          <div className="settings-empty-card">
            <strong>No organization settings available</strong>
            <span>Your current role does not manage organization settings.</span>
          </div>
        )}
      </div>
    </>
  );
}
