import type { NetworkStatus } from "@/hooks/use-network-status";

export function ConnectionStatus({ status }: { status: NetworkStatus }) {
  const label = status === "ONLINE" ? "Online" : status === "OFFLINE" ? "Offline" : "Checking";
  return <span className={`pos-connection is-${status.toLowerCase()}`}><i aria-hidden="true" />{label}</span>;
}
