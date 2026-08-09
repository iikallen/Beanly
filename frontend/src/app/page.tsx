import Link from "next/link";

import { Brand } from "@/components/auth-shell";

export const dynamic = "force-dynamic";

export default async function Home() {
  const apiUrl = process.env.API_URL ?? "http://localhost:8000";
  const connected = await fetch(`${apiUrl}/health/ready`, { cache: "no-store" })
    .then((response) => response.ok)
    .catch(() => false);

  return (
    <main className="home-shell">
      <Brand />
      <h1>Beanly</h1>
      <p className={connected ? "status-ok" : "status-error"}>
        Backend connected {connected ? "✓" : "— unavailable"}
      </p>
      <div className="home-actions">
        <Link className="primary-link" href="/register">Create account</Link>
        <Link className="secondary-link" href="/login">Log in</Link>
      </div>
    </main>
  );
}
