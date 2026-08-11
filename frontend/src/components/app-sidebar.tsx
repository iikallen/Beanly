"use client";

import {
  BarChart3,
  Building2,
  Coffee,
  Landmark,
  Package,
  LayoutDashboard,
  LogOut,
  Monitor,
  ReceiptText,
  Settings as SettingsIcon,
  ShoppingCart,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { Brand } from "@/components/auth-shell";
import { useWorkspace } from "@/components/workspace-provider";

export function AppSidebar({
  active,
  teamView,
  onTeamView,
  settingsCanReadIntegrations,
  settingsCanReadFiscal,
}: {
  active: "dashboard" | "analytics" | "pos" | "fiscal" | "inventory" | "menu" | "purchasing" | "finance" | "team" | "settings";
  teamView?: "employees" | "invitations";
  onTeamView?: (view: "employees" | "invitations") => void;
  settingsCanReadIntegrations?: boolean;
  settingsCanReadFiscal?: boolean;
}) {
  const {
    organizations,
    locations,
    currentOrganization,
    currentLocation,
    selectOrganization,
    selectLocation,
  } = useWorkspace();
  const { logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  if (!currentOrganization || !currentLocation) return null;

  return (
    <aside className="app-sidebar">
      <Brand />
      <label className="switcher organization-switcher">
        <span className="switcher-label">Organization</span>
        <span className="switcher-icon" aria-hidden="true"><Building2 /></span>
        <select
          aria-label="Organization"
          value={currentOrganization.id}
          onChange={async (event) => {
            if (event.target.value === "create") {
              router.push("/onboarding?new=1");
              return;
            }
            await selectOrganization(event.target.value);
          }}
        >
          {organizations.map((organization) => (
            <option key={organization.id} value={organization.id}>
              {organization.name}
            </option>
          ))}
          <option value="create">+ Create organization</option>
        </select>
      </label>

      <nav className="app-nav" aria-label="Main navigation">
        <button
          className={active === "dashboard" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app")}
        >
          <LayoutDashboard aria-hidden="true" />
          Dashboard
        </button>
        <button
          className={active === "analytics" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/analytics")}
        >
          <BarChart3 aria-hidden="true" />
          Analytics
        </button>
        {active === "analytics" && (
          <div className="app-subnav analytics-subnav" aria-label="Analytics navigation">
            <Link className={pathname === "/app/analytics" ? "is-active" : ""} href="/app/analytics">Overview</Link>
            <Link className={pathname === "/app/analytics/products" ? "is-active" : ""} href="/app/analytics/products">Products</Link>
            <Link className={pathname === "/app/analytics/menu-engineering" ? "is-active" : ""} href="/app/analytics/menu-engineering">Menu Engineering</Link>
            <Link className={pathname === "/app/analytics/hours" ? "is-active" : ""} href="/app/analytics/hours">Sales by Hour</Link>
            <Link className={pathname === "/app/analytics/inventory" ? "is-active" : ""} href="/app/analytics/inventory">Inventory Consumption</Link>
            <Link className={pathname === "/app/analytics/locations" ? "is-active" : ""} href="/app/analytics/locations">Locations</Link>
          </div>
        )}
        <button
          className={active === "pos" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/pos")}
        >
          <Monitor aria-hidden="true" />
          POS
        </button>
        {active === "fiscal" && <button className="app-nav-item is-active" type="button" onClick={() => router.push("/app/fiscal")}><ReceiptText aria-hidden="true" />Fiscal</button>}
        <button
          className={active === "team" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/team")}
        >
          <Users aria-hidden="true" />
          Team
        </button>
        {active === "team" && onTeamView && (
          <div className="app-subnav" aria-label="Team navigation">
            <button
              className={teamView === "employees" ? "is-active" : ""}
              type="button"
              onClick={() => onTeamView("employees")}
            >
              Employees
            </button>
            <button
              className={teamView === "invitations" ? "is-active" : ""}
              type="button"
              onClick={() => onTeamView("invitations")}
            >
              Invitations
            </button>
          </div>
        )}
        <button
          className={active === "inventory" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/inventory")}
        >
          <Package aria-hidden="true" />
          Inventory
        </button>
        {active === "inventory" && (
          <div className="app-subnav inventory-subnav" aria-label="Inventory navigation">
            <Link className={pathname === "/app/inventory" ? "is-active" : ""} href="/app/inventory">
              Overview
            </Link>
            <Link className={pathname.startsWith("/app/inventory/movements") ? "is-active" : ""} href="/app/inventory/movements">
              Movements
            </Link>
            <Link className={pathname.startsWith("/app/inventory/write-offs") ? "is-active" : ""} href="/app/inventory/write-offs">
              Write-offs
            </Link>
            <Link className={pathname.startsWith("/app/inventory/counts") ? "is-active" : ""} href="/app/inventory/counts">
              Inventory Counts
            </Link>
            <Link className={pathname.startsWith("/app/inventory/transfers") ? "is-active" : ""} href="/app/inventory/transfers">
              Transfers
            </Link>
          </div>
        )}
        <button
          className={active === "purchasing" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/purchasing/orders")}
        >
          <ShoppingCart aria-hidden="true" />
          Purchasing
        </button>
        {active === "purchasing" && (
          <div className="app-subnav purchasing-subnav" aria-label="Purchasing navigation">
            <Link
              className={pathname.startsWith("/app/purchasing/orders") ? "is-active" : ""}
              href="/app/purchasing/orders"
            >
              Purchase Orders
            </Link>
            <Link
              className={pathname.startsWith("/app/purchasing/receipts") ? "is-active" : ""}
              href="/app/purchasing/receipts"
            >
              Goods Receipts
            </Link>
            <Link
              className={pathname.startsWith("/app/purchasing/returns") ? "is-active" : ""}
              href="/app/purchasing/returns"
            >
              Supplier Returns
            </Link>
            <Link
              className={pathname.startsWith("/app/purchasing/suppliers") ? "is-active" : ""}
              href="/app/purchasing/suppliers"
            >
              Suppliers
            </Link>
          </div>
        )}
        <button
          className={active === "finance" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/finance")}
        >
          <Landmark aria-hidden="true" />
          Finance
        </button>
        {active === "finance" && (
          <div className="app-subnav finance-subnav" aria-label="Finance navigation">
            <Link className={pathname === "/app/finance" ? "is-active" : ""} href="/app/finance">
              Overview
            </Link>
            <Link className={pathname.startsWith("/app/finance/pnl") ? "is-active" : ""} href="/app/finance/pnl">
              P&amp;L
            </Link>
            <Link className={pathname.startsWith("/app/finance/expenses") ? "is-active" : ""} href="/app/finance/expenses">
              Expenses
            </Link>
            <Link className={pathname.startsWith("/app/finance/cash-flow") ? "is-active" : ""} href="/app/finance/cash-flow">
              Cash Flow
            </Link>
            <Link className={pathname.startsWith("/app/finance/accounts") ? "is-active" : ""} href="/app/finance/accounts">
              Accounts
            </Link>
          </div>
        )}
        <button
          className={active === "menu" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/menu/products")}
        >
          <Coffee aria-hidden="true" />
          Menu
        </button>
        {active === "menu" && (
          <div className="app-subnav menu-subnav" aria-label="Menu navigation">
            <Link
              className={pathname.startsWith("/app/menu/products") ? "is-active" : ""}
              href="/app/menu/products"
            >
              Products
            </Link>
            <Link
              className={pathname.startsWith("/app/menu/categories") ? "is-active" : ""}
              href="/app/menu/categories"
            >
              Categories
            </Link>
          </div>
        )}
        <button
          className={active === "settings" ? "app-nav-item is-active" : "app-nav-item"}
          type="button"
          onClick={() => router.push("/app/settings")}
        >
          <SettingsIcon aria-hidden="true" />
          Settings
        </button>
        {active === "settings" && (
          <div className="app-subnav settings-subnav" aria-label="Settings navigation">
            <Link className={pathname === "/app/settings" ? "is-active" : ""} href="/app/settings">
              General
            </Link>
            {settingsCanReadIntegrations && (
              <Link
                className={pathname.startsWith("/app/settings/integrations") ? "is-active" : ""}
                href="/app/settings/integrations"
              >
                Integrations
              </Link>
            )}
            {settingsCanReadFiscal && (
              <>
                <Link className={pathname === "/app/fiscal" ? "is-active" : ""} href="/app/fiscal">Fiscal Operations</Link>
                <Link className={pathname.startsWith("/app/settings/fiscal") ? "is-active" : ""} href="/app/settings/fiscal">Fiscal &amp; Taxes</Link>
              </>
            )}
          </div>
        )}
      </nav>

      <label className="location-switcher">
        <span>Location</span>
        <select
          value={currentLocation.id}
          onChange={(event) => selectLocation(event.target.value)}
        >
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.name}
            </option>
          ))}
        </select>
      </label>

      <button
        className="logout-button"
        type="button"
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
      >
        <LogOut aria-hidden="true" />
        Log out
      </button>
    </aside>
  );
}
