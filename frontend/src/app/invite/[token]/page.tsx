"use client";

import { Building2, CheckCircle2, Mail } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Brand } from "@/components/auth-shell";
import { useWorkspace } from "@/components/workspace-provider";
import { api, type PublicInvitation } from "@/lib/api";

export default function InvitationPage() {
  const { token } = useParams<{ token: string }>();
  const { user, accessToken, loading: authLoading } = useAuth();
  const { refreshWorkspaces } = useWorkspace();
  const router = useRouter();
  const [invitation, setInvitation] = useState<PublicInvitation | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.inspectInvitation(token)
      .then((result) => {
        if (!cancelled) setInvitation(result);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Invitation unavailable");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [token]);

  const next = encodeURIComponent(`/invite/${token}`);
  const invitedEmail = invitation ? encodeURIComponent(invitation.email) : "";

  return (
    <main className="invite-page">
      <Brand />
      <section className="invite-card">
        {loading ? (
          <p>Loading invitation…</p>
        ) : error && !invitation ? (
          <>
            <h1>Invitation unavailable</h1>
            <p className="invite-error">{error}</p>
            <Link className="secondary-button invite-home" href="/">Back to Beanly</Link>
          </>
        ) : invitation ? (
          <>
            <div className="invite-mark"><Mail aria-hidden="true" /></div>
            <p className="eyebrow">You’re invited</p>
            <h1>Join {invitation.organization_name}</h1>
            <p className="invite-copy">
              Accept your invitation to work in Beanly as <strong>{titleCase(invitation.role)}</strong>.
            </p>
            <div className="invite-details">
              <div><Building2 aria-hidden="true" /><span>Organization</span><strong>{invitation.organization_name}</strong></div>
              <div><CheckCircle2 aria-hidden="true" /><span>Account</span><strong>{invitation.email}</strong></div>
            </div>
            {authLoading ? (
              <p>Checking your account…</p>
            ) : !user ? (
              <div className="invite-auth-actions">
                <Link className="primary-link" href={`/login?next=${next}&email=${invitedEmail}`}>Log in to accept</Link>
                <Link className="secondary-button" href={`/register?next=${next}&email=${invitedEmail}`}>Create account</Link>
              </div>
            ) : user.email.toLowerCase() !== invitation.email.toLowerCase() ? (
              <p className="invite-error">
                This invitation belongs to {invitation.email}. Log in with that account to accept it.
              </p>
            ) : (
              <button
                className="primary-button"
                type="button"
                disabled={accepting || !accessToken}
                onClick={async () => {
                  if (!accessToken) return;
                  setAccepting(true);
                  setError("");
                  try {
                    await api.acceptInvitation(token, accessToken);
                    refreshWorkspaces();
                    router.replace("/app");
                  } catch (caught) {
                    setError(caught instanceof Error ? caught.message : "Unable to accept invitation");
                    setAccepting(false);
                  }
                }}
              >
                {accepting ? "Joining…" : "Accept invitation"}
              </button>
            )}
            {error && <p className="invite-error" role="alert">{error}</p>}
          </>
        ) : null}
      </section>
    </main>
  );
}

function titleCase(value: string) {
  return value.charAt(0) + value.slice(1).toLowerCase();
}
