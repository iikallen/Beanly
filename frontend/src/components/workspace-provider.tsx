"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import {
  api,
  type CreatedWorkspace,
  type CreateWorkspaceInput,
  type Location,
  type Organization,
} from "@/lib/api";

type WorkspaceContextValue = {
  loading: boolean;
  error: string;
  organizations: Organization[];
  locations: Location[];
  currentOrganization: Organization | null;
  currentLocation: Location | null;
  createWorkspace: (input: CreateWorkspaceInput) => Promise<CreatedWorkspace>;
  selectOrganization: (organizationId: string) => Promise<void>;
  selectLocation: (locationId: string) => void;
  refreshWorkspaces: () => void;
};

type StoredSelection = {
  version: 1;
  organizationId: string;
  locationId: string;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { user, accessToken, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [currentOrganization, setCurrentOrganization] =
    useState<Organization | null>(null);
  const [currentLocation, setCurrentLocation] = useState<Location | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const userId = user?.id;

  useEffect(() => {
    let cancelled = false;
    if (authLoading) return;

    async function loadWorkspace() {
      await Promise.resolve();
      if (cancelled) return;
      if (!userId || !accessToken) {
        setOrganizations([]);
        setLocations([]);
        setCurrentOrganization(null);
        setCurrentLocation(null);
        setError("");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");
      const stored = readSelection(userId);
      try {
        const availableOrganizations = await api.listOrganizations(accessToken);
        if (cancelled) return;
        setOrganizations(availableOrganizations);
        const organization =
          availableOrganizations.find((item) => item.id === stored?.organizationId) ??
          availableOrganizations[0] ??
          null;
        setCurrentOrganization(organization);
        if (!organization) {
          setLocations([]);
          setCurrentLocation(null);
          return;
        }
        const availableLocations = await api.listLocations(organization.id, accessToken);
        if (cancelled) return;
        setLocations(availableLocations);
        const location =
          availableLocations.find((item) => item.id === stored?.locationId) ??
          availableLocations.find((item) => item.is_primary) ??
          availableLocations[0] ??
          null;
        setCurrentLocation(location);
        if (location) writeSelection(userId, organization.id, location.id);
      } catch (caught) {
        if (cancelled) return;
        setOrganizations([]);
        setLocations([]);
        setCurrentOrganization(null);
        setCurrentLocation(null);
        setError(caught instanceof Error ? caught.message : "Unable to load workspace");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadWorkspace();
    return () => {
      cancelled = true;
    };
  }, [accessToken, authLoading, refreshKey, userId]);

  const refreshWorkspaces = useCallback(() => {
    setLoading(true);
    setRefreshKey((current) => current + 1);
  }, []);

  const createWorkspace = useCallback(
    async (input: CreateWorkspaceInput) => {
      if (!accessToken || !userId) throw new Error("Authentication required");
      const created = await api.createWorkspace(input, accessToken);
      setOrganizations((current) => [...current, created.organization]);
      setLocations([created.location]);
      setCurrentOrganization(created.organization);
      setCurrentLocation(created.location);
      writeSelection(userId, created.organization.id, created.location.id);
      return created;
    },
    [accessToken, userId],
  );

  const selectOrganization = useCallback(
    async (organizationId: string) => {
      if (!accessToken || !userId) return;
      const organization = organizations.find((item) => item.id === organizationId);
      if (!organization) return;
      const availableLocations = await api.listLocations(organization.id, accessToken);
      const location =
        availableLocations.find((item) => item.is_primary) ??
        availableLocations[0] ??
        null;
      setCurrentOrganization(organization);
      setLocations(availableLocations);
      setCurrentLocation(location);
      if (location) writeSelection(userId, organization.id, location.id);
    },
    [accessToken, organizations, userId],
  );

  const selectLocation = useCallback(
    (locationId: string) => {
      if (!userId || !currentOrganization) return;
      const location = locations.find((item) => item.id === locationId);
      if (!location) return;
      setCurrentLocation(location);
      writeSelection(userId, currentOrganization.id, location.id);
    },
    [currentOrganization, locations, userId],
  );

  return (
    <WorkspaceContext.Provider
      value={{
        loading,
        error,
        organizations,
        locations,
        currentOrganization,
        currentLocation,
        createWorkspace,
        selectOrganization,
        selectLocation,
        refreshWorkspaces,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used inside WorkspaceProvider");
  }
  return context;
}

function storageKey(userId: string) {
  return `beanly.workspace.${userId}`;
}

function readSelection(userId: string): StoredSelection | null {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey(userId)) ?? "null");
    if (
      value?.version === 1 &&
      typeof value.organizationId === "string" &&
      typeof value.locationId === "string"
    ) {
      return value as StoredSelection;
    }
  } catch {
    localStorage.removeItem(storageKey(userId));
  }
  return null;
}

function writeSelection(userId: string, organizationId: string, locationId: string) {
  localStorage.setItem(
    storageKey(userId),
    JSON.stringify({ version: 1, organizationId, locationId } satisfies StoredSelection),
  );
}
