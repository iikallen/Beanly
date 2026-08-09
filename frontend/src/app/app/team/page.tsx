"use client";

import { MoreVertical, Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import {
  api,
  type Invitation,
  type MembershipRole,
  type Team,
  type TeamMember,
} from "@/lib/api";

type Tab = "employees" | "invitations";

const ROLE_DESCRIPTIONS: Record<Exclude<MembershipRole, "OWNER">, string> = {
  ADMIN: "Manages the team, locations, and daily operations.",
  MANAGER: "Runs day-to-day operations and can view the team.",
  ACCOUNTANT: "Accesses financial, payment, and analytics information.",
  CASHIER: "Creates sales and payments at assigned locations.",
  BARISTA: "Creates sales and sees limited inventory information.",
};

export default function TeamPage() {
  const { user, accessToken, loading: authLoading } = useAuth();
  const { loading: workspaceLoading, error: workspaceError, currentOrganization, locations } =
    useWorkspace();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("employees");
  const [team, setTeam] = useState<Team | null>(null);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [profile, setProfile] = useState<TeamMember | null>(null);

  const loadTeam = useCallback(async () => {
    if (!accessToken || !currentOrganization) return;
    try {
      const nextTeam = await api.getTeam(currentOrganization.id, accessToken);
      setTeam(nextTeam);
      setInvitations(nextTeam.invitations);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load team");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization]);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, router, user]);

  useEffect(() => {
    if (!accessToken || !currentOrganization) return;
    let cancelled = false;
    api.getTeam(currentOrganization.id, accessToken)
      .then((nextTeam) => {
        if (cancelled) return;
        setTeam(nextTeam);
        setInvitations(nextTeam.invitations);
        setError("");
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to load team");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  const currentRole = useMemo(
    () => team?.members.find((member) => member.user_id === user?.id)?.role,
    [team, user?.id],
  );
  const canInvite = team?.permissions.includes("team.invite") ?? false;
  const canRemove = team?.permissions.includes("team.remove") ?? false;

  if (authLoading || workspaceLoading || !user) {
    return <main className="loading-state">Loading…</main>;
  }
  if (workspaceError) {
    return <main className="loading-state error-state">{workspaceError}</main>;
  }
  if (!currentOrganization) {
    return <main className="loading-state">Preparing workspace…</main>;
  }

  return (
    <main className="app-shell">
      <AppSidebar active="team" teamView={tab} onTeamView={setTab} />
      <section className="team-content">
        <header className="team-header">
          <div>
            <h1>Team</h1>
            <p>Manage employees and Beanly access.</p>
          </div>
          {canInvite && (
            <button className="invite-button" type="button" onClick={() => setInviteOpen(true)}>
              <Plus aria-hidden="true" />
              Invite member
            </button>
          )}
        </header>

        <div className="team-tabs" role="tablist" aria-label="Team views">
          <button
            className={tab === "employees" ? "is-active" : ""}
            type="button"
            role="tab"
            aria-selected={tab === "employees"}
            onClick={() => setTab("employees")}
          >
            Employees
          </button>
          <button
            className={tab === "invitations" ? "is-active" : ""}
            type="button"
            role="tab"
            aria-selected={tab === "invitations"}
            onClick={() => setTab("invitations")}
          >
            Invitations
          </button>
        </div>

        {error && <div className="team-alert" role="alert">{error}</div>}
        {loading ? (
          <div className="team-empty">Loading team…</div>
        ) : tab === "employees" ? (
          <EmployeeTable members={team?.members ?? []} onOpen={setProfile} />
        ) : (
          <InvitationTable
            invitations={invitations}
            canRemove={canRemove}
            onRevoke={async (invitation) => {
              if (!accessToken) return;
              try {
                await api.revokeInvitation(
                  invitation.id,
                  currentOrganization.id,
                  accessToken,
                );
                await loadTeam();
              } catch (caught) {
                setError(caught instanceof Error ? caught.message : "Unable to revoke invitation");
              }
            }}
          />
        )}
      </section>

      {inviteOpen && (
        <InviteModal
          locations={locations}
          currentRole={currentRole}
          onClose={() => setInviteOpen(false)}
          onSubmit={async (email, role, locationIds) => {
            if (!accessToken) return;
            await api.createInvitation(
              { email, role, location_ids: locationIds },
              currentOrganization.id,
              accessToken,
            );
            setInviteOpen(false);
            setTab("invitations");
            await loadTeam();
          }}
        />
      )}
      {profile && <ProfileModal member={profile} onClose={() => setProfile(null)} />}
    </main>
  );
}

function EmployeeTable({
  members,
  onOpen,
}: {
  members: TeamMember[];
  onOpen: (member: TeamMember) => void;
}) {
  if (members.length === 0) return <div className="team-empty">No employees yet.</div>;
  return (
    <div className="team-table-wrap">
      <table className="team-table">
        <thead><tr><th>Name</th><th>Role</th><th>Locations</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.employee_id ?? member.user_id}>
              <td><strong>{member.first_name} {member.last_name}</strong><span>{member.email}</span></td>
              <td>{member.role ?? "Employee"}</td>
              <td>{member.location_access === "ALL" ? "All locations" : member.locations.join(", ") || "—"}</td>
              <td><span className={`status-pill status-${member.status.toLowerCase()}`}>{titleCase(member.status)}</span></td>
              <td><button className="icon-button" type="button" aria-label={`Open ${member.first_name} profile`} onClick={() => onOpen(member)}><MoreVertical /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InvitationTable({
  invitations,
  canRemove,
  onRevoke,
}: {
  invitations: Invitation[];
  canRemove: boolean;
  onRevoke: (invitation: Invitation) => Promise<void>;
}) {
  if (invitations.length === 0) {
    return <div className="team-empty">No invitations yet.</div>;
  }
  return (
    <div className="team-table-wrap">
      <table className="team-table invitation-table">
        <thead><tr><th>Email</th><th>Role</th><th>Expires</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {invitations.map((invitation) => (
            <tr key={invitation.id}>
              <td><strong>{invitation.email}</strong></td>
              <td>{invitation.role}</td>
              <td>{new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(invitation.expires_at))}</td>
              <td><span className={`status-pill status-${invitation.status.toLowerCase()}`}>{titleCase(invitation.status)}</span></td>
              <td>{canRemove && invitation.status === "PENDING" && <button className="text-button" type="button" onClick={() => void onRevoke(invitation)}>Revoke</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InviteModal({
  locations,
  currentRole,
  onClose,
  onSubmit,
}: {
  locations: Array<{ id: string; name: string }>;
  currentRole: MembershipRole | null | undefined;
  onClose: () => void;
  onSubmit: (
    email: string,
    role: Exclude<MembershipRole, "OWNER">,
    locationIds: string[],
  ) => Promise<void>;
}) {
  const roles: Array<Exclude<MembershipRole, "OWNER">> = currentRole === "OWNER"
    ? ["ADMIN", "MANAGER", "ACCOUNTANT", "CASHIER", "BARISTA"]
    : ["MANAGER", "ACCOUNTANT", "CASHIER", "BARISTA"];
  const [role, setRole] = useState<Exclude<MembershipRole, "OWNER">>(roles[0]);
  const [selected, setSelected] = useState<string[]>(locations[0] ? [locations[0].id] : []);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(String(data.get("email")), role, selected);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to send invitation");
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal-card invite-modal" role="dialog" aria-modal="true" aria-labelledby="invite-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" aria-label="Close" onClick={onClose}><X /></button>
        <h2 id="invite-title">Invite team member</h2>
        <form onSubmit={submit}>
          <label className="modal-field"><span>Email</span><input name="email" type="email" autoComplete="email" placeholder="anna@example.com" required autoFocus /></label>
          <label className="modal-field"><span>Role</span><select value={role} onChange={(event) => setRole(event.target.value as Exclude<MembershipRole, "OWNER">)}>{roles.map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}</select></label>
          <fieldset className="location-options"><legend>Locations</legend>{locations.map((location) => <label key={location.id}><input type="checkbox" checked={selected.includes(location.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, location.id] : current.filter((id) => id !== location.id))} /><span>{location.name}</span></label>)}</fieldset>
          <p className="role-description">{ROLE_DESCRIPTIONS[role]}</p>
          <div className="form-message" role="alert">{error || (selected.length === 0 ? "Select at least one location." : "")}</div>
          <div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="invite-button" type="submit" disabled={submitting || selected.length === 0}>{submitting ? "Sending…" : "Send invitation"}</button></div>
        </form>
      </section>
    </div>
  );
}

function ProfileModal({ member, onClose }: { member: TeamMember; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal-card profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" aria-label="Close" onClick={onClose}><X /></button>
        <p className="eyebrow">Employee profile</p>
        <h2 id="profile-title">{member.first_name} {member.last_name}</h2>
        <dl>
          <div><dt>Role</dt><dd>{member.role ? titleCase(member.role) : "Employee"}</dd></div>
          <div><dt>Position</dt><dd>{member.position ?? "Not specified"}</dd></div>
          <div><dt>Locations</dt><dd>{member.location_access === "ALL" ? "All locations" : member.locations.join(", ") || "—"}</dd></div>
          <div><dt>Status</dt><dd>{titleCase(member.status)}</dd></div>
          <div><dt>Phone</dt><dd>{member.phone ?? "Not specified"}</dd></div>
          <div><dt>Beanly account</dt><dd>{member.user_id ? "Connected" : "Not connected"}</dd></div>
          {member.email && <div><dt>Email</dt><dd>{member.email}</dd></div>}
        </dl>
      </section>
    </div>
  );
}

function titleCase(value: string) {
  return value.charAt(0) + value.slice(1).toLowerCase();
}
