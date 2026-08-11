import type { PaymentMethodChoice } from "@/lib/api";

import { assertPublicCatalog } from "./catalog";
import type { OfflineSession, PublicCatalogSnapshot } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class OfflineApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type SessionWire = Omit<OfflineSession, "clock_offset_ms" | "catalog_snapshot" | "shell"> & {
  catalog_snapshot: Omit<PublicCatalogSnapshot, "public_payload"> & { payload: PublicCatalogSnapshot["public_payload"] };
};

export type SessionShell = OfflineSession["shell"];

export async function pingOfflineApi(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}/api/v1/pos/offline/ping`, {
      credentials: "include",
      cache: "no-store",
      signal: signal ?? AbortSignal.timeout(5000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function pairDevice(
  registerId: string,
  name: string,
  organizationId: string,
  accessToken: string,
): Promise<void> {
  await request("/api/v1/pos/offline/devices/pair", {
    method: "POST",
    body: JSON.stringify({ register_id: registerId, name }),
    headers: authorization(organizationId, accessToken),
  });
}

export async function revokeDevice(deviceId: string, organizationId: string, accessToken: string): Promise<void> {
  await request(`/api/v1/pos/offline/devices/${deviceId}/revoke`, {
    method: "POST",
    headers: authorization(organizationId, accessToken),
  });
}

export async function startOfflineSession(
  shiftId: string,
  organizationId: string,
  accessToken: string,
  shell: SessionShell,
): Promise<OfflineSession> {
  const response = await request<SessionWire>("/api/v1/pos/offline/sessions/start", {
    method: "POST",
    body: JSON.stringify({ shift_id: shiftId }),
    headers: authorization(organizationId, accessToken),
  });
  return normalizeSession(response, shell);
}

export async function currentOfflineSession(shell: SessionShell): Promise<OfflineSession | null> {
  const response = await fetch(`${API_URL}/api/v1/pos/offline/sessions/current`, {
    credentials: "include",
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw await responseError(response);
  const body = await response.json() as SessionWire | null;
  return body ? normalizeSession(body, shell) : null;
}

export async function refreshOfflineSession(sessionId: string, shell: SessionShell): Promise<OfflineSession> {
  const response = await request<SessionWire>(`/api/v1/pos/offline/sessions/${sessionId}/refresh`, { method: "POST" });
  return normalizeSession(response, shell);
}

export async function closeOfflineSession(sessionId: string): Promise<void> {
  await request(`/api/v1/pos/offline/sessions/${sessionId}/close`, { method: "POST" });
}

function normalizeSession(response: SessionWire, shell: SessionShell): OfflineSession {
  const serverTime = Date.parse(response.server_time);
  return {
    ...response,
    clock_offset_ms: Number.isFinite(serverTime) ? serverTime - Date.now() : 0,
    catalog_snapshot: {
      ...response.catalog_snapshot,
      public_payload: assertPublicCatalog(response.catalog_snapshot.payload),
    },
    shell,
  };
}

async function request<T = unknown>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: { "content-type": "application/json", ...init.headers },
  });
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function responseError(response: Response) {
  const body = await response.json().catch(() => null) as { detail?: string | { message?: string }; message?: string } | null;
  const detail = typeof body?.detail === "string" ? body.detail : body?.detail?.message;
  return new OfflineApiError(response.status, detail ?? body?.message ?? `Request failed (${response.status})`);
}

function authorization(organizationId: string, accessToken: string) {
  return { authorization: `Bearer ${accessToken}`, "X-Organization-ID": organizationId };
}

export function defaultPaymentMethods(): PaymentMethodChoice[] {
  return [
    { code: "CASH", name: "Cash" },
    { code: "CARD", name: "Card" },
    { code: "OTHER", name: "Other" },
  ];
}
