import type { KitchenTicket, KitchenTicketStatus } from "@/lib/api";

export function mergeKitchenTickets(current: KitchenTicket[], incoming: KitchenTicket[], replace = false) {
  if (replace) return [...incoming].sort(byFireTime);
  const values = new Map(current.map((ticket) => [ticket.id, ticket]));
  for (const ticket of incoming) values.set(ticket.id, ticket);
  return [...values.values()].sort(byFireTime);
}

export function kitchenAging(firedAt: string, now: number, warningSeconds: number, lateSeconds: number) {
  const elapsedSeconds = Math.max(0, Math.floor((now - new Date(firedAt).getTime()) / 1000));
  return { elapsedSeconds, level: elapsedSeconds >= lateSeconds ? "late" : elapsedSeconds >= warningSeconds ? "warning" : "normal" } as const;
}

export function kitchenProductionLabel(status: KitchenTicketStatus | null) {
  if (!status) return "Paid · queued";
  return `Paid · ${status.charAt(0)}${status.slice(1).toLowerCase()}`;
}

function byFireTime(left: KitchenTicket, right: KitchenTicket) {
  return new Date(left.fired_at).getTime() - new Date(right.fired_at).getTime();
}
