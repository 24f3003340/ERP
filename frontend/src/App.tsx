import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, Row, setToken, setUnauthorizedHandler, getToken } from "./api";
import { getLocale, setLocale, t } from "./i18n";
import { SessionCtx, ToastProvider, useToast } from "./ui";
import Dashboard from "./pages/Dashboard";
import Billing from "./pages/Billing";
import Invoices from "./pages/Invoices";
import Products from "./pages/Products";
import Purchases from "./pages/Purchases";
import Parties from "./pages/Parties";
import Accounts from "./pages/Accounts";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import { AuthScreen } from "./pages/Auth";

const NAV: [string, string, string, string][] = [
  ["/", "home", "🏠", "sales.view"], ["/billing", "billing", "🧾", "sales.create"], ["/invoices", "invoices", "📄", "sales.view"],
  ["/products", "products", "📦", "products.view"], ["/purchases", "purchases", "🚚", "purchases.view"],
  ["/customers", "customers", "👥", "parties.view"], ["/suppliers", "suppliers", "🏭", "parties.view"],
  ["/accounts", "accounts", "💰", "accounts.view"], ["/reports", "reports", "📊", "reports.view"], ["/settings", "settings", "⚙️", "settings"],
];

function Shell({ session, onLogout }: { session: { user: Row; business: Row; refresh: () => Promise<void> }; onLogout: () => void }) {
  const [, force] = useState(0);
  const can = useCallback((p: string) => {
    const perms: string[] = session.user.permissions || [];
    return perms.includes("*") || perms.includes(p) || (p === "settings" && (perms.includes("backup.create") || perms.includes("audit.view")));
  }, [session.user]);
  const [diagWarn, setDiagWarn] = useState("");
  useEffect(() => {
    if (!can("backup.create")) return;
    api("/diagnostics").then((d) => {
      if (d.low_disk) setDiagWarn("Low disk space — free some space to keep backups and invoices safe.");
      else if (!d.last_backup) setDiagWarn("No backup yet. Create one in Settings → Backup.");
      else if (Date.now() - new Date(d.last_backup.at).getTime() > 2 * 86400000) setDiagWarn("Last backup is older than 2 days.");
      else if (!d.healthy) setDiagWarn("Data consistency check failed — open Settings → Diagnostics.");
    }).catch(() => {});
  }, [can]);
  return (
    <SessionCtx.Provider value={{ ...session, can }}>
      <div className="app">
        <aside className="side">
          <div className="brand">🧮 {session.business.name}</div>
          <nav>
            {NAV.filter((n) => can(n[3])).map(([to, key, icon]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => "nav" + (isActive ? " active" : "")}>
                <span aria-hidden>{icon}</span> {t(key)}
              </NavLink>
            ))}
          </nav>
          <div className="side-foot">
            <div className="who">{session.user.full_name || session.user.username}<small>{session.user.role}</small></div>
            <button className="btn ghost sm" onClick={() => { setLocale(getLocale() === "en" ? "hi" : "en"); force((x) => x + 1); }}>
              {getLocale() === "en" ? "हिंदी" : "English"}
            </button>
            <button className="btn ghost sm" onClick={onLogout}>{t("logout")}</button>
          </div>
        </aside>
        <main className="main">
          {diagWarn && <div className="banner warn">{diagWarn}</div>}
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/billing" element={<Billing />} />
            <Route path="/invoices" element={<Invoices />} />
            <Route path="/products" element={<Products />} />
            <Route path="/purchases" element={<Purchases />} />
            <Route path="/customers" element={<Parties kind="customer" />} />
            <Route path="/suppliers" element={<Parties kind="supplier" />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </SessionCtx.Provider>
  );
}

function Root() {
  const [state, setState] = useState<"loading" | "setup" | "login" | "in" | "down">("loading");
  const [session, setSession] = useState<{ user: Row; business: Row } | null>(null);
  const nav = useNavigate();
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const st = await api("/status");
      if (st.needs_setup) return setState("setup");
      if (!getToken()) return setState("login");
      const me = await api("/me");
      setSession(me);
      setState("in");
    } catch (e: any) {
      if (getToken() && e.message !== "Session expired, please login again") setState("down");
      else { setToken(null); setState("login"); }
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    setUnauthorizedHandler(() => { setToken(null); setState("login"); toast("Session expired, please login again", "err"); });
  }, [toast]);

  if (state === "loading") return <div className="center-screen">Loading…</div>;
  if (state === "down") return <div className="center-screen">Cannot reach server. <button className="btn" onClick={load}>Retry</button></div>;
  if (state === "setup" || state === "login") return <AuthScreen mode={state} onDone={(tok) => { setToken(tok); load(); nav("/"); }} />;
  return <Shell session={{ ...session!, refresh: load }} onLogout={() => { setToken(null); setState("login"); }} />;
}

export default function App() {
  return (<ToastProvider><Root /></ToastProvider>);
}
