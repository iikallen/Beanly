"use client";

import { AlertTriangle, RefreshCcw } from "lucide-react";

import type { IntegrationJob } from "@/lib/api";
import {
  formatIntegrationDate,
  integrationJobLabel,
  integrationStatusClass,
  integrationStatusLabel,
} from "@/lib/integrations";

export function IntegrationJobList({
  jobs,
  loading,
  workingId,
  canRetry,
  onRetry,
}: {
  jobs: IntegrationJob[];
  loading: boolean;
  workingId: string;
  canRetry: boolean;
  onRetry: (job: IntegrationJob) => void;
}) {
  if (loading && jobs.length === 0) {
    return <div className="integration-state is-compact">Loading activity…</div>;
  }
  if (jobs.length === 0) {
    return <div className="integration-state is-compact">No integration activity matches these filters.</div>;
  }

  return <div className="integration-job-list">{jobs.map((job) => {
    const latestAttempt = job.attempt_history.at(-1);
    return <article key={job.id}>
      <div className="integration-job-time"><strong>{formatIntegrationDate(job.created_at)}</strong><span>{job.attempts} {job.attempts === 1 ? "attempt" : "attempts"}</span></div>
      <div className="integration-job-copy"><strong>{integrationJobLabel(job.job_type)}</strong><span>{job.source_type} · {job.source_id.slice(0, 8)}</span>{job.last_error_message && <small><AlertTriangle aria-hidden="true" />{job.last_error_code ? `${job.last_error_code}: ` : ""}{job.last_error_message}</small>}</div>
      <div className="integration-job-outcome"><span className={integrationStatusClass(job.status)}><i aria-hidden="true" />{integrationStatusLabel(job.status)}</span>{latestAttempt?.duration_ms != null && <small>{latestAttempt.duration_ms} ms</small>}</div>
      {canRetry && job.status === "DEAD" && <button className="integration-retry-button" type="button" disabled={workingId === job.id} onClick={() => onRetry(job)}><RefreshCcw aria-hidden="true" />{workingId === job.id ? "Retrying…" : "Retry"}</button>}
    </article>;
  })}</div>;
}
