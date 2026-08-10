"use client";

import { AlertTriangle, ArrowLeft, CheckCircle2, PlugZap, RefreshCcw, Unplug } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { IntegrationJobList } from "@/components/integrations/integration-job-list";
import { useWorkspace } from "@/components/workspace-provider";
import { useIntegrationPermissions } from "@/hooks/use-integration-permissions";
import {
  api,
  type IntegrationCapability,
  type IntegrationConnection,
  type IntegrationJob,
  type IntegrationJobList as IntegrationJobListResponse,
  type IntegrationLocationBinding,
  type IntegrationProvider,
  type Location,
} from "@/lib/api";
import {
  formatIntegrationDate,
  integrationCapabilityLabel,
  integrationStatusClass,
  integrationStatusLabel,
} from "@/lib/integrations";

export default function IntegrationConnectionPage() {
  const { connectionId } = useParams<{ connectionId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const permissions = useIntegrationPermissions();
  const [connection, setConnection] = useState<IntegrationConnection | null>(null);
  const [provider, setProvider] = useState<IntegrationProvider | null>(null);
  const [jobs, setJobs] = useState<IntegrationJobListResponse | null>(null);
  const [connectionOrganizationId, setConnectionOrganizationId] = useState<string | null>(null);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [workingId, setWorkingId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization || permissions.loading || !permissions.canRead) return;
    setLoading(true);
    setError("");
    setConnectionOrganizationId(currentOrganization.id);
    setConnection(null);
    try {
      const [nextConnection, providers] = await Promise.all([
        api.getIntegrationConnection(connectionId, currentOrganization.id, accessToken),
        api.listIntegrationProviders(currentOrganization.id, accessToken),
      ]);
      setConnection(nextConnection);
      setConnectionOrganizationId(currentOrganization.id);
      setProvider(providers.find((item) => item.code === nextConnection.provider_code) ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load connection");
    } finally {
      setLoading(false);
    }
  }, [accessToken, connectionId, currentOrganization, permissions.canRead, permissions.loading]);

  const loadJobs = useCallback(async () => {
    if (!accessToken || !currentOrganization || connectionOrganizationId !== currentOrganization.id || !connection?.can_manage) return;
    setJobsLoading(true);
    try {
      setJobs(await api.listIntegrationJobs(currentOrganization.id, accessToken, {
        connectionId,
        limit: "10",
        offset: "0",
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load recent activity");
    } finally {
      setJobsLoading(false);
    }
  }, [accessToken, connection?.can_manage, connectionId, connectionOrganizationId, currentOrganization]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  useEffect(() => { void Promise.resolve().then(loadJobs); }, [loadJobs]);

  async function updateName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !connection?.can_manage) return;
    const displayName = String(new FormData(event.currentTarget).get("display_name") ?? "").trim();
    if (!displayName) return;
    await run("name", "Connection name updated.", () => api.updateIntegrationConnection(
      connection.id,
      { display_name: displayName },
      currentOrganization.id,
      accessToken,
    ));
  }

  async function replaceCredentials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !connection?.can_manage || !apiKey.trim()) return;
    const nextApiKey = apiKey.trim();
    setApiKey("");
    const succeeded = await run("credentials", "Credentials replaced. The saved value cannot be viewed.", () => api.updateIntegrationConnection(
      connection.id,
      { credentials: { api_key: nextApiKey } },
      currentOrganization.id,
      accessToken,
    ));
    if (succeeded) setCredentialsOpen(false);
  }

  async function testConnection() {
    if (!accessToken || !currentOrganization || !connection?.can_manage) return;
    await run("test", "Connection test finished.", () => api.testIntegrationConnection(connection.id, currentOrganization.id, accessToken));
  }

  async function disconnect() {
    if (!accessToken || !currentOrganization || !connection?.can_manage) return;
    if (!window.confirm(`Disconnect ${connection.display_name}? Existing activity will be kept.`)) return;
    await run("disconnect", "Connection disconnected.", () => api.disconnectIntegrationConnection(connection.id, currentOrganization.id, accessToken));
  }

  async function saveBinding(locationId: string, capability: IntegrationCapability, externalLocationId: string) {
    if (!accessToken || !currentOrganization || !connection?.can_manage) return;
    const key = `${locationId}:${capability}`;
    setWorkingId(key);
    setError("");
    setNotice("");
    try {
      const binding = await api.setIntegrationLocationBinding(connection.id, locationId, {
        capability,
        external_location_id: externalLocationId.trim() || undefined,
        settings: {},
        is_active: true,
      }, currentOrganization.id, accessToken);
      setConnection((current) => current ? {
        ...current,
        bindings: [...current.bindings.filter((item) => item.location_id !== locationId || item.capability !== capability), binding],
      } : current);
      setNotice("Location binding saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save location binding");
    } finally {
      setWorkingId("");
    }
  }

  async function deleteBinding(locationId: string, capability: IntegrationCapability) {
    if (!accessToken || !currentOrganization || !connection?.can_manage) return;
    const key = `${locationId}:${capability}`;
    setWorkingId(key);
    setError("");
    setNotice("");
    try {
      await api.deleteIntegrationLocationBinding(connection.id, locationId, capability, currentOrganization.id, accessToken);
      setConnection((current) => current ? {
        ...current,
        bindings: current.bindings.filter((item) => item.location_id !== locationId || item.capability !== capability),
      } : current);
      setNotice("Location binding removed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to remove location binding");
    } finally {
      setWorkingId("");
    }
  }

  async function retry(job: IntegrationJob) {
    if (!accessToken || !currentOrganization || !connection?.can_manage) return;
    setWorkingId(job.id);
    setError("");
    try {
      const updated = await api.retryIntegrationJob(job.id, currentOrganization.id, accessToken);
      setJobs((current) => current ? { ...current, items: current.items.map((item) => item.id === job.id ? updated : item) } : current);
      setNotice("Job queued again with the same idempotency key.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to retry job");
    } finally {
      setWorkingId("");
    }
  }

  async function run(id: string, success: string, action: () => Promise<IntegrationConnection>) {
    setWorkingId(id);
    setError("");
    setNotice("");
    try {
      setConnection(await action());
      setNotice(success);
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update connection");
      return false;
    } finally {
      setWorkingId("");
    }
  }

  if (permissions.loading || loading || connectionOrganizationId !== currentOrganization?.id) return <div className="integration-state">Loading connection…</div>;
  if (!permissions.canRead) return <div className="integration-state is-error" role="alert"><strong>Integrations are restricted.</strong><span>Your role does not include integration access.</span></div>;
  if (error && !connection) return <div className="integration-state is-error" role="alert"><strong>Connection could not be loaded.</strong><span>{error}</span><Link href="/app/settings/integrations">Back to integrations</Link></div>;
  if (!connection) return null;

  const capabilities = provider?.capabilities ?? uniqueCapabilities(connection.bindings);

  return (
    <>
      <Link className="integration-back" href="/app/settings/integrations"><ArrowLeft aria-hidden="true" />Integrations</Link>
      <header className="settings-header integration-detail-header">
        <div>
          <p className="settings-eyebrow">{provider?.name ?? connection.provider_code}</p>
          <h1>{connection.display_name}</h1>
          <span className={integrationStatusClass(connection.status)}><i aria-hidden="true" />{integrationStatusLabel(connection.status)}</span>
        </div>
        {connection.can_manage && <div className="integration-header-actions">{provider?.supports_health_check && connection.status !== "REVOKED" && <button className="integration-secondary-button" type="button" disabled={workingId === "test"} onClick={() => void testConnection()}><RefreshCcw className={workingId === "test" ? "is-spinning" : ""} aria-hidden="true" />{workingId === "test" ? "Testing…" : "Test connection"}</button>}{connection.status !== "REVOKED" && <button className="integration-danger-button" type="button" disabled={workingId === "disconnect"} onClick={() => void disconnect()}><Unplug aria-hidden="true" />Disconnect</button>}</div>}
      </header>

      <div className="integration-live-region" aria-live="polite">{notice}</div>
      {error && <div className="integration-alert is-error" role="alert">{error}</div>}
      {notice && <div className="integration-alert is-success"><CheckCircle2 aria-hidden="true" />{notice}</div>}

      {connection.status === "DEGRADED" && <section className="integration-degraded" role="status"><AlertTriangle aria-hidden="true" /><div><strong>Connection needs attention</strong><p>{connection.last_error_message ?? "The latest provider request failed."}</p>{connection.last_error_code && <small>Error code: {connection.last_error_code}</small>}</div>{connection.can_manage && <button className="integration-secondary-button" type="button" onClick={() => { setCredentialsOpen(true); requestAnimationFrame(() => document.getElementById("replacement-api-key")?.focus()); }}>Reconnect</button>}</section>}

      <div className="integration-detail-grid">
        <section className="integration-panel" aria-labelledby="connection-details-heading">
          <div className="integration-panel-heading"><div><h2 id="connection-details-heading">Connection</h2><p>Provider identity and current health.</p></div><PlugZap aria-hidden="true" /></div>
          {connection.can_manage ? <form className="integration-name-form" onSubmit={updateName}><label className="integration-field"><span>Display name</span><input name="display_name" maxLength={150} required defaultValue={connection.display_name} /></label><button className="integration-secondary-button" type="submit" disabled={workingId === "name"}>{workingId === "name" ? "Saving…" : "Save"}</button></form> : <dl className="integration-meta"><div><dt>Display name</dt><dd>{connection.display_name}</dd></div></dl>}
          <dl className="integration-meta">
            <div><dt>Provider</dt><dd>{provider?.name ?? connection.provider_code}</dd></div>
            <div><dt>Last successful request</dt><dd>{formatIntegrationDate(connection.last_success_at)}</dd></div>
            <div><dt>Last health check</dt><dd>{formatIntegrationDate(connection.last_health_check_at)}</dd></div>
            <div><dt>Connected</dt><dd>{formatIntegrationDate(connection.connected_at)}</dd></div>
          </dl>
        </section>

        <section className="integration-panel" id="credentials" aria-labelledby="credentials-heading">
          <div className="integration-panel-heading"><div><h2 id="credentials-heading">Credentials</h2><p>Saved secrets are never returned by the API.</p></div><ShieldIcon /></div>
          <div className="integration-secret-summary"><span>API key</span><strong aria-label={connection.has_credentials ? "Credentials saved" : "No credentials saved"}>{connection.has_credentials ? "••••••••••••" : "Not set"}</strong></div>
          {connection.can_manage && !credentialsOpen && <button className="integration-secondary-button" type="button" onClick={() => setCredentialsOpen(true)}>Replace credentials</button>}
          {connection.can_manage && credentialsOpen && <form className="integration-credential-form" onSubmit={replaceCredentials}><label className="integration-field"><span>New API key</span><input id="replacement-api-key" type="password" autoComplete="new-password" required value={apiKey} onChange={(event) => setApiKey(event.target.value)} /><small>The old value cannot be retrieved.</small></label><div><button className="integration-secondary-button" type="button" onClick={() => { setApiKey(""); setCredentialsOpen(false); }}>Cancel</button><button className="integration-primary-button" type="submit" disabled={workingId === "credentials" || !apiKey.trim()}>{workingId === "credentials" ? "Replacing…" : "Replace"}</button></div></form>}
        </section>
      </div>

      {provider?.location_scoped !== false && <section className="integration-panel integration-locations" aria-labelledby="locations-heading">
        <div className="integration-panel-heading"><div><h2 id="locations-heading">Locations</h2><p>Choose where each provider capability is active.</p></div></div>
        {capabilities.length === 0 ? <div className="integration-state is-compact">This provider has no location-scoped capability.</div> : capabilities.map((capability) => <div className="integration-capability-bindings" key={capability}><h3>{integrationCapabilityLabel(capability)}</h3>{locations.map((location) => { const binding = connection.bindings.find((item) => item.location_id === location.id && item.capability === capability); return <LocationBindingRow key={`${location.id}:${capability}:${binding?.is_active}:${binding?.external_location_id ?? ""}`} location={location} capability={capability} binding={binding} canManage={connection.can_manage} busy={workingId === `${location.id}:${capability}`} onSave={saveBinding} onDelete={deleteBinding} />; })}</div>)}
      </section>}

      {connection.can_manage && <section className="integration-activity" aria-labelledby="recent-activity-heading">
        <div className="integration-section-heading"><div><h2 id="recent-activity-heading">Recent activity</h2><p>Latest jobs for this connection.</p></div><Link href="/app/settings/integrations#activity-heading">View all</Link></div>
        <IntegrationJobList jobs={jobs?.items ?? []} loading={jobsLoading} workingId={workingId} canRetry={connection.can_manage} onRetry={retry} />
      </section>}
    </>
  );
}

function LocationBindingRow({ location, capability, binding, canManage, busy, onSave, onDelete }: {
  location: Location;
  capability: IntegrationCapability;
  binding?: IntegrationLocationBinding;
  canManage: boolean;
  busy: boolean;
  onSave: (locationId: string, capability: IntegrationCapability, externalLocationId: string) => Promise<void>;
  onDelete: (locationId: string, capability: IntegrationCapability) => Promise<void>;
}) {
  const [externalId, setExternalId] = useState(binding?.external_location_id ?? "");
  const active = binding?.is_active ?? false;

  return <div className="integration-location-row">
    <label className="integration-location-toggle"><input type="checkbox" checked={active} disabled={!canManage || busy} onChange={(event) => { if (event.target.checked) void onSave(location.id, capability, externalId); else void onDelete(location.id, capability); }} /><span><strong>{location.name}</strong><small>{active ? "Active" : "Not connected"}</small></span></label>
    <label className="integration-field"><span>External location ID <small>Optional</small></span><input value={externalId} maxLength={255} disabled={!canManage || !active || busy} onChange={(event) => setExternalId(event.target.value)} /></label>
    {canManage && <button className="integration-secondary-button" type="button" disabled={!active || busy || externalId === (binding?.external_location_id ?? "")} onClick={() => void onSave(location.id, capability, externalId)}>{busy ? "Saving…" : "Save"}</button>}
  </div>;
}

function uniqueCapabilities(bindings: IntegrationLocationBinding[]) {
  return [...new Set(bindings.map((binding) => binding.capability))];
}

function ShieldIcon() {
  return <span className="integration-lock" aria-hidden="true">•••</span>;
}
