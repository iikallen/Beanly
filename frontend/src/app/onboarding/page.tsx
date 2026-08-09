"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Brand } from "@/components/auth-shell";
import { useWorkspace } from "@/components/workspace-provider";

export default function OnboardingPage() {
  const { user, loading } = useAuth();
  const { createWorkspace } = useWorkspace();
  const router = useRouter();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, router, user]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await createWorkspace({
        name: String(data.get("name")),
        country_code: String(data.get("country_code")),
        currency_code: String(data.get("currency_code")),
        first_location: {
          name: String(data.get("location_name")),
          timezone: String(data.get("timezone")),
          address: String(data.get("address")),
        },
      });
      router.replace("/app");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create coffee shop");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || !user) {
    return <main className="loading-state">Loading…</main>;
  }

  return (
    <main className="onboarding-shell">
      <div className="onboarding-content">
        <Brand />
        <h1>Welcome to Beanly</h1>
        <form className="onboarding-form" onSubmit={submit}>
          <OnboardingField label="Business name">
            <input name="name" placeholder="Coffee Point" maxLength={150} required />
          </OnboardingField>
          <OnboardingField label="Country">
            <select name="country_code" defaultValue="KZ">
              <option value="KZ">Kazakhstan</option>
            </select>
          </OnboardingField>
          <OnboardingField label="Currency">
            <select name="currency_code" defaultValue="KZT">
              <option value="KZT">KZT</option>
            </select>
          </OnboardingField>
          <OnboardingField label="First location">
            <input name="location_name" placeholder="Dostyk" maxLength={150} required />
          </OnboardingField>
          <OnboardingField label="Timezone">
            <select name="timezone" defaultValue="Asia/Almaty">
              <option value="Asia/Almaty">Asia/Almaty</option>
            </select>
          </OnboardingField>
          <OnboardingField label="Address (optional)">
            <input name="address" placeholder="Dostyk 123" maxLength={1000} />
          </OnboardingField>
          <div className="form-message onboarding-message" role="alert">
            {error}
          </div>
          <button className="primary-button onboarding-submit" disabled={submitting} type="submit">
            {submitting ? "Creating coffee shop…" : "Create coffee shop"}
          </button>
        </form>
      </div>
    </main>
  );
}

function OnboardingField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="onboarding-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
