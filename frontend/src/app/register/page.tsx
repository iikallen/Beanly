"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { AuthShell } from "@/components/auth-shell";
import { FormField } from "@/components/form-field";
import { useAuth } from "@/components/auth-provider";

export default function RegisterPage() {
  return (
    <Suspense fallback={<main className="loading-state">Loading…</main>}>
      <RegisterForm />
    </Suspense>
  );
}

function RegisterForm() {
  const { register } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [email, setEmail] = useState(() => searchParams.get("email") ?? "");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await register({
        email: String(data.get("email")),
        password: String(data.get("password")),
        first_name: String(data.get("first_name")),
        last_name: String(data.get("last_name")),
      });
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next?.startsWith("/") ? next : "/onboarding");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell>
      <h1>Create account</h1>
      <form className="auth-form" onSubmit={submit}>
        <FormField
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <FormField
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={128}
          required
        />
        <FormField label="First name" name="first_name" autoComplete="given-name" required />
        <FormField label="Last name" name="last_name" autoComplete="family-name" required />
        <div className="form-message" role="alert">{error}</div>
        <button className="primary-button" disabled={submitting} type="submit">
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="auth-switch">Already have an account? <Link href="/login">Log in</Link></p>
    </AuthShell>
  );
}
