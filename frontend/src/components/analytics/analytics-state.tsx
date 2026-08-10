"use client";

import { AlertCircle, BarChart3 } from "lucide-react";

export function AnalyticsLoading() {
  return <div className="analytics-loading" aria-busy="true" aria-live="polite"><span className="sr-only">Loading analytics…</span><div className="analytics-loading-grid">{Array.from({ length: 4 }, (_, index) => <i key={index} />)}</div><i /></div>;
}

export function AnalyticsError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="analytics-state is-error" role="alert"><AlertCircle aria-hidden="true" /><strong>Analytics could not be loaded.</strong><span>{message}</span><button type="button" onClick={onRetry}>Try again</button></div>;
}

export function AnalyticsEmpty({ message = "No analytics are available for this period yet." }: { message?: string }) {
  return <div className="analytics-state"><BarChart3 aria-hidden="true" /><strong>No data yet</strong><span>{message}</span></div>;
}

export function AnalyticsAccessState() {
  return <div className="analytics-state"><AlertCircle aria-hidden="true" /><strong>Analytics access required</strong><span>Your role cannot view historical analytics.</span></div>;
}
