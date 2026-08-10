import type {
  IntegrationCapability,
  IntegrationConnectionStatus,
  IntegrationJobStatus,
} from "@/lib/api";

const STATUS_LABELS: Record<IntegrationConnectionStatus | IntegrationJobStatus, string> = {
  PENDING: "Pending",
  ACTIVE: "Connected",
  DEGRADED: "Needs attention",
  REVOKED: "Disconnected",
  PROCESSING: "Processing",
  RETRYING: "Retrying",
  SUCCESS: "Succeeded",
  DEAD: "Failed",
};

export function integrationStatusLabel(status: IntegrationConnectionStatus | IntegrationJobStatus) {
  return STATUS_LABELS[status];
}

export function integrationStatusClass(status: IntegrationConnectionStatus | IntegrationJobStatus) {
  return `integration-status is-${status.toLowerCase()}`;
}

export function integrationCapabilityLabel(capability: IntegrationCapability) {
  return capability.charAt(0) + capability.slice(1).toLowerCase();
}

export function integrationJobLabel(jobType: string) {
  const value = jobType.replaceAll("_", " ").toLowerCase();
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function formatIntegrationDate(value: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
