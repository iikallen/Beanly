import type { Metadata } from "next";

import { AuthProvider } from "@/components/auth-provider";
import { WorkspaceProvider } from "@/components/workspace-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Beanly",
  description: "Coffee shop management",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <WorkspaceProvider>{children}</WorkspaceProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
