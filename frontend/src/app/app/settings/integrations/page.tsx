"use client";

import { ArrowRight, PlugZap, Plus, RefreshCcw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

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
  type IntegrationJobStatus,
  type IntegrationProvider,
} from "@/lib/api";
import {
  integrationCapabilityLabel,
  integrationStatusClass,
  integrationStatusLabel,
} from "@/lib/integrations";

const CAPABILITIES: IntegrationCapability[] = ["FISCAL", "PAYMENT", "DELIVERY", "NOTIFICATION"];

type JobFilters = {
  status: IntegrationJobStatus | "";
  jobType: string;
  dateFrom: string;
  dateTo: string;
};

const EMPTY_JOB_FILTERS: JobFilters = { status: "", jobType: "", dateFrom: "", dateTo: "" };

export default function IntegrationsPage() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const permissions = useIntegrationPermissions();
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [connections, setConnections] = useState<IntegrationConnection[]>([]);
  const [jobs, setJobs] = useState<IntegrationJobListResponse | null>(null);
  const [catalogOrganizationId, setCatalogOrganizationId] = useState<string | null>(null);
  const [jobsOrganizationId, setJobsOrganizationId] = useState<string | null>(null);
  const [filters, setFilters] = useState<JobFilters>(EMPTY_JOB_FILTERS);
  const [connectProvider, setConnectProvider] = useState<IntegrationProvider | null>(null);
  const [loading, setLoading] = useState(true);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [workingId, setWorkingId] = useState("");
  const [error, setError] = useState("");

  const loadCatalog = useCallback(async () => {
    if (!accessToken || !currentOrganization || permissions.loading || !permissions.canRead) return;
    setLoading(true);
    setError("");
    setCatalogOrganizationId(currentOrganization.id);
    setProviders([]);
    setConnections([]);
    try {
      const [nextProviders, nextConnections] = await Promise.all([
        api.listIntegrationProviders(currentOrganization.id, accessToken),
        api.listIntegrationConnections(currentOrganization.id, accessToken),
      ]);
      setProviders(nextProviders);
      setConnections(nextConnections);
      setCatalogOrganizationId(currentOrganization.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load integrations");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization, permissions.canRead, permissions.loading]);

  const loadJobs = useCallback(async (nextFilters: JobFilters) => {
    if (!accessToken || !currentOrganization || !permissions.canWrite) return;
    setJobsLoading(true);
    setJobsOrganizationId(currentOrganization.id);
    setJobs(null);
    try {
      const nextJobs = await api.listIntegrationJobs(currentOrganization.id, accessToken, {
        ...nextFilters,
        limit: "50",
        offset: "0",
      });
      setJobs(nextJobs);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load integration activity");
    } finally {
      setJobsLoading(false);
    }
  }, [accessToken, currentOrganization, permissions.canWrite]);

  useEffect(() => { void Promise.resolve().then(loadCatalog); }, [loadCatalog]);
  useEffect(() => {
    if (permissions.canWrite) void Promise.resolve().then(() => loadJobs(EMPTY_JOB_FILTERS));
  }, [loadJobs, permissions.canWrite]);

  const connectionsByProvider = useMemo(() => {
    const result = new Map<string, IntegrationConnection[]>();
    for (const connection of connections) {
      result.set(connection.provider_code, [...(result.get(connection.provider_code) ?? []), connection]);
    }
    return result;
  }, [connections]);

  async function createConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !connectProvider) return;
    const data = new FormData(event.currentTarget);
    const apiKey = String(data.get("api_key") ?? "").trim();
    const secretInput = event.currentTarget.elements.namedItem("api_key");
    const displayName = String(data.get("display_name") ?? "").trim();
    if (connectProvider.auth_type === "API_KEY" && !apiKey) return;
    if (secretInput instanceof HTMLInputElement) secretInput.value = "";
    setWorkingId("create");
    setError("");
    try {
      const connection = await api.createIntegrationConnection({
        provider_code: connectProvider.code,
        display_name: displayName,
        config: { environment: "sandbox" },
        ...(connectProvider.auth_type === "API_KEY" ? { credentials: { api_key: apiKey } } : {}),
      }, currentOrganization.id, accessToken);
      router.push(`/app/settings/integrations/${connection.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create connection");
    } finally {
      setWorkingId("");
    }
  }

  async function retry(job: IntegrationJob) {
    if (!accessToken || !currentOrganization || !permissions.canWrite) return;
    setWorkingId(job.id);
    setError("");
    try {
      const updated = await api.retryIntegrationJob(job.id, currentOrganization.id, accessToken);
      setJobs((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === updated.id ? updated : item),
      } : current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to retry job");
    } finally {
      setWorkingId("");
    }
  }

  if (permissions.loading || catalogOrganizationId !== currentOrganization?.id) return <div className="integration-state">Loading integrations…</div>;
  if (!permissions.canRead) {
    return <div className="integration-state is-error" role="alert"><strong>Integrations are restricted.</strong><span>Your role does not include integration access.</span></div>;
  }

  return (
    <>
      <header className="settings-header integration-page-header">
        <div>
          <h1>Integrations</h1>
          <p>Connect providers without exposing credentials to anyone after they are saved.</p>
        </div>
        <span className="integration-security-note"><ShieldCheck aria-hidden="true" />Secrets are write-only</span>
      </header>

      {error && <div className="integration-alert is-error" role="alert">{error}</div>}

      {loading ? <div className="integration-state">Loading provider catalog…</div> : (
        <div className="integration-catalog">
          {CAPABILITIES.map((capability) => {
            const capabilityProviders = providers.filter((provider) => provider.capabilities.includes(capability));
            return (
              <section className="integration-category" key={capability} aria-labelledby={`capability-${capability}`}>
                <div className="integration-section-heading">
                  <div><h2 id={`capability-${capability}`}>{integrationCapabilityLabel(capability)}</h2><p>{capabilityDescription(capability)}</p></div>
                </div>
                <div className="integration-provider-grid">
                  {capabilityProviders.length === 0 ? (
                    <article className="integration-provider-card is-coming-soon">
                      <span className="integration-provider-icon" aria-hidden="true"><PlugZap /></span>
                      <div><strong>Coming soon</strong><p>No {integrationCapabilityLabel(capability).toLowerCase()} provider is available yet.</p></div>
                    </article>
                  ) : capabilityProviders.map((provider) => {
                    const providerConnections = connectionsByProvider.get(provider.code) ?? [];
                    return (
                      <article className="integration-provider-card" key={provider.code}>
                        <span className="integration-provider-icon" aria-hidden="true"><PlugZap /></span>
                        <div className="integration-provider-copy">
                          <div><strong>{provider.name}</strong><small>{provider.auth_type === "API_KEY" ? "API key" : provider.auth_type === "OAUTH2" ? "OAuth 2" : "No credentials"}</small></div>
                          {providerConnections.length === 0 ? <p>Not connected</p> : providerConnections.map((connection) => {
                            const boundNames = connection.bindings
                              .filter((binding) => binding.is_active && binding.capability === capability)
                              .map((binding) => locations.find((location) => location.id === binding.location_id)?.name)
                              .filter(Boolean);
                            return (
                              <Link className="integration-connection-link" href={`/app/settings/integrations/${connection.id}`} key={connection.id}>
                                <span><strong>{connection.display_name}</strong><small>{boundNames.length ? boundNames.join(", ") : "No locations"}</small></span>
                                <span className={integrationStatusClass(connection.status)}><i aria-hidden="true" />{integrationStatusLabel(connection.status)}</span>
                                <ArrowRight aria-hidden="true" />
                              </Link>
                            );
                          })}
                        </div>
                        {providerConnections.length === 0 && permissions.canWrite && (
                          <button className="integration-secondary-button" type="button" onClick={() => setConnectProvider(provider)}><Plus aria-hidden="true" />Connect</button>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {permissions.canWrite && (
        <section className="integration-activity" aria-labelledby="activity-heading">
          <div className="integration-section-heading">
            <div><h2 id="activity-heading">Activity log</h2><p>Provider delivery state without raw responses or credentials.</p></div>
            <span>{jobs && jobsOrganizationId === currentOrganization?.id ? `Showing ${jobs.items.length} of ${jobs.total}` : ""}</span>
          </div>
          <form className="integration-job-filters" onSubmit={(event) => { event.preventDefault(); void loadJobs(filters); }}>
            <label><span>Status</span><select value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as IntegrationJobStatus | "" }))}><option value="">All statuses</option><option value="PENDING">Pending</option><option value="PROCESSING">Processing</option><option value="RETRYING">Retrying</option><option value="SUCCESS">Succeeded</option><option value="DEAD">Failed</option></select></label>
            <label><span>Job type</span><input value={filters.jobType} onChange={(event) => setFilters((current) => ({ ...current, jobType: event.target.value }))} placeholder="FISCALIZE_PAYMENT" /></label>
            <label><span>From</span><input type="date" value={filters.dateFrom} onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))} /></label>
            <label><span>To</span><input type="date" value={filters.dateTo} onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))} /></label>
            <button className="integration-secondary-button" type="submit" disabled={jobsLoading}><RefreshCcw className={jobsLoading ? "is-spinning" : ""} aria-hidden="true" />Apply</button>
          </form>
          <IntegrationJobList jobs={jobsOrganizationId === currentOrganization?.id ? jobs?.items ?? [] : []} workingId={workingId} canRetry={permissions.canWrite} onRetry={retry} loading={jobsLoading || jobsOrganizationId !== currentOrganization?.id} />
        </section>
      )}

      {connectProvider && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setConnectProvider(null)}>
          <form className="modal-card integration-connect-modal" role="dialog" aria-modal="true" aria-labelledby="connect-title" aria-describedby="connect-description" onSubmit={createConnection} onMouseDown={(event) => event.stopPropagation()} onKeyDown={(event) => { if (event.key === "Escape") setConnectProvider(null); }}>
            <h2 id="connect-title">Connect {connectProvider.name}</h2>
            <p id="connect-description">Credentials are encrypted on save and cannot be viewed again.</p>
            <label className="integration-field"><span>Display name</span><input name="display_name" maxLength={150} required autoFocus placeholder={`${connectProvider.name} · Main`} /></label>
            {connectProvider.auth_type === "API_KEY" && <label className="integration-field"><span>API key</span><input name="api_key" type="password" autoComplete="new-password" required /><small>Write-only. Replace it later if needed.</small></label>}
            <div className="modal-actions"><button className="integration-secondary-button" type="button" onClick={() => setConnectProvider(null)}>Cancel</button><button className="integration-primary-button" type="submit" disabled={workingId === "create"}>{workingId === "create" ? "Connecting…" : "Connect"}</button></div>
          </form>
        </div>
      )}
    </>
  );
}

function capabilityDescription(capability: IntegrationCapability) {
  if (capability === "FISCAL") return "Fiscal receipts and provider delivery health.";
  if (capability === "PAYMENT") return "External payment providers.";
  if (capability === "DELIVERY") return "Delivery marketplaces and order transport.";
  return "Operational notifications and alerts.";
}
