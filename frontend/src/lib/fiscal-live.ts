import type { ExternalPaymentAttemptStatus, FiscalReceiptStatus } from "@/lib/api";

export type SafeOperationAction = "NONE" | "START" | "RETRY" | "RECONCILE";

export function paymentAttemptAction(status: ExternalPaymentAttemptStatus): SafeOperationAction {
  if (status === "CREATED") return "START";
  if (status === "UNKNOWN" || status === "TERMINAL_PENDING") return "RECONCILE";
  if (status === "DECLINED" || status === "CANCELLED") return "RETRY";
  return "NONE";
}

export function fiscalReceiptAction(status: FiscalReceiptStatus): SafeOperationAction {
  if (status === "UNKNOWN") return "RECONCILE";
  if (status === "DEAD") return "RETRY";
  return "NONE";
}

export function fiscalStatusLabel(status: FiscalReceiptStatus) {
  const labels: Record<FiscalReceiptStatus, string> = {
    PENDING: "Pending",
    PROCESSING: "Processing",
    SUCCEEDED: "Issued",
    RETRYING: "Retrying",
    UNKNOWN: "Result unknown",
    DEAD: "Needs attention",
  };
  return labels[status];
}

export function terminalStatusCopy(status: ExternalPaymentAttemptStatus) {
  if (status === "APPROVED") return "Payment approved";
  if (status === "DECLINED") return "Payment declined";
  if (status === "CANCELLED") return "Payment cancelled";
  if (status === "UNKNOWN") return "Payment result unknown";
  if (status === "TERMINAL_PENDING") return "Waiting for customer…";
  return "Ready to send to terminal";
}

export function safeReceiptUrl(value: string | null) {
  try {
    const url = new URL(value ?? "");
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}
