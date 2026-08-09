"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AuthShell } from "@/components/auth-shell";
import { FormField } from "@/components/form-field";

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="loading-state">Loading…</main>}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const { login } = useAuth();
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
      await login(String(data.get("email")), String(data.get("password")));
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next?.startsWith("/") ? next : "/app");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to log in.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell>
      <h1>Welcome back</h1>
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
          autoComplete="current-password"
          maxLength={128}
          required
        />
        <div className="form-message" role="alert">{error}</div>
        <button className="primary-button" disabled={submitting} type="submit">
          {submitting ? "Logging in…" : "Log in"}
        </button>
      </form>
      <p className="auth-switch">New to Beanly? <Link href="/register">Create account</Link></p>
    </AuthShell>
  );
}
