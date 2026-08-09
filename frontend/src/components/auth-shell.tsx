import Link from "next/link";

export function Brand() {
  return (
    <Link className="brand" href="/" aria-label="Beanly home">
      <svg aria-hidden="true" viewBox="0 0 32 32">
        <path d="M5 21C7 10 15 5 27 5c0 12-6 20-17 21" />
        <path d="M7 25c5-6 10-10 17-15" />
      </svg>
      <span>Beanly</span>
    </Link>
  );
}
export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="auth-shell">
      <div className="auth-content">
        <Brand />
        {children}
      </div>
    </main>
  );
}
