import { useState } from "react";
import { api, download, fdt, Row, ROLES } from "../api";
import { Badge, Empty, Field, Loading, Table, useAsync, useSession, useToast } from "../ui";

export default function Settings() {
  const { can } = useSession();
  const tabs: [string, string, string][] = [["biz", "Business", "users.manage"], ["users", "Users & roles", "users.manage"], ["backup", "Backup & restore", "backup.create"], ["diag", "Diagnostics", "backup.create"], ["audit", "Audit log", "audit.view"]];
  const avail = tabs.filter((t) => can(t[2]));
  const [tab, setTab] = useState(avail[0]?.[0] || "");
  return (
    <div>
      <div className="page-head"><h2>Settings</h2></div>
      <div className="tabs">{avail.map(([k, l]) => <button key={k} className={"tab" + (tab === k ? " active" : "")} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === "biz" && <Biz />}{tab === "users" && <Users />}{tab === "backup" && <Backup />}{tab === "diag" && <Diag />}{tab === "audit" && <Audit />}
    </div>
  );
}

function Biz() {
  const { business, refresh } = useSession(); const toast = useToast();
  const [f, setF] = useState<Row>({ ...business }); const [err, setErr] = useState("");
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  async function save() {
    try { await api("/business", { method: "PUT", body: { ...f, max_cashier_discount_pct: Number(f.max_cashier_discount_pct) } }); toast("Settings saved"); localStorage.setItem("erp_locale", f.locale); refresh(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="card narrow">
      <Field label="Business name"><input value={f.name} onChange={set("name")} /></Field>
      <div className="grid2"><Field label="GSTIN"><input value={f.gstin} onChange={set("gstin")} /></Field><Field label="Phone"><input value={f.phone} onChange={set("phone")} /></Field></div>
      <div className="grid2"><Field label="Address"><input value={f.address} onChange={set("address")} /></Field>
        <Field label="State code (2 digits)" hint="Needed to choose CGST+SGST vs IGST"><input maxLength={2} value={f.state_code} onChange={set("state_code")} /></Field></div>
      <div className="grid2"><Field label="Invoice prefix"><input value={f.invoice_prefix} onChange={set("invoice_prefix")} maxLength={10} /></Field>
        <Field label="Cashier max discount %" hint="Above this a manager must bill"><input type="number" min="0" max="100" value={f.max_cashier_discount_pct} onChange={set("max_cashier_discount_pct")} /></Field></div>
      <Field label="Invoice footer"><input value={f.footer} onChange={set("footer")} /></Field>
      <label className="check"><input type="checkbox" checked={f.allow_negative_stock} onChange={set("allow_negative_stock")} /> Allow selling when stock is zero (negative stock)</label>
      <label className="check"><input type="checkbox" checked={f.round_total} onChange={set("round_total")} /> Round invoice total to nearest rupee</label>
      {err && <div className="error">{err}</div>}
      <button className="btn primary" onClick={save}>Save settings</button>
    </div>
  );
}

function Users() {
  const toast = useToast();
  const { data, loading, reload } = useAsync(() => api("/users"), []);
  const [f, setF] = useState({ username: "", full_name: "", password: "", role: "cashier" }); const [err, setErr] = useState("");
  async function add() { try { await api("/users", { body: f }); toast("User created"); setF({ username: "", full_name: "", password: "", role: "cashier" }); setErr(""); reload(); } catch (e: any) { setErr(e.message); } }
  async function patch(u: Row, p: Row) { try { await api("/users/" + u.id, { method: "PUT", body: { username: u.username, full_name: u.full_name, role: u.role, active: u.active, ...p } }); reload(); } catch (e: any) { toast(e.message, "err"); } }
  return (
    <div>
      <div className="card"><h3>Add user</h3><div className="grid4">
        <Field label="Username"><input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field>
        <Field label="Full name"><input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Password (8+)"><input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Field label="Role"><select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field></div>
        {err && <div className="error">{err}</div>}<button className="btn primary" onClick={add} disabled={f.username.length < 3 || f.password.length < 8}>Create user</button></div>
      {loading ? <Loading /> : <Table head={["Username", "Name", "Role", "Active", ""]}>{data?.map((u: Row) => (
        <tr key={u.id}><td>{u.username}</td><td>{u.full_name}</td>
          <td><select value={u.role} onChange={(e) => patch(u, { role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></td>
          <td>{u.active ? <Badge tone="ok">active</Badge> : <Badge tone="err">disabled</Badge>}</td>
          <td className="actions"><button className="btn sm" onClick={() => patch(u, { active: !u.active })}>{u.active ? "Disable" : "Enable"}</button>
            <button className="btn sm" onClick={() => { const p = prompt("New password (min 8 chars) for " + u.username); if (p) patch(u, { password: p }); }}>Reset password</button></td></tr>))}</Table>}
    </div>
  );
}

function Backup() {
  const { can } = useSession(); const toast = useToast();
  const { data, loading, reload } = useAsync(() => api("/backups"), []);
  const [busy, setBusy] = useState(false);
  async function create() { setBusy(true); try { const r = await api("/backups", { method: "POST" }); toast("Backup created: " + r.name); reload(); } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); } }
  async function verify(n: string) { try { const v = await api(`/backups/${n}/verify`, { method: "POST" }); toast(v.ok ? `Backup OK — ${v.invoices ?? ""} invoices, ${v.products ?? ""} products` : "Backup FAILED verification", v.ok ? "ok" : "err"); } catch (e: any) { toast(e.message, "err"); } }
  async function restore(n: string) {
    if (!confirm(`Restore ${n}?\n\nThe current data will be replaced by this backup. A safety backup of the current data is created first.`)) return;
    try { await api(`/backups/${n}/restore`, { method: "POST" }); toast("Restored. Reloading…"); setTimeout(() => location.reload(), 1200); } catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <div>
      <div className={"banner" + (data && !data.encrypted ? "" : " ok")}>{data?.encrypted ? "🔒 Backups are encrypted (AES). Keep the passphrase safe — without it they cannot be restored. " : "Backups are NOT encrypted — set ERP_BACKUP_PASSPHRASE to enable encryption. "}Automatic backup runs daily (last 14 kept). Also copy backups to a pen drive regularly — a backup on the same disk does not protect against disk failure. Try restoring on a test copy before you need it.</div>
      <div className="actions" style={{ margin: "8px 0" }}><button className="btn primary" disabled={busy} onClick={create}>{busy ? "Creating…" : "Create backup now"}</button></div>
      {loading ? <Loading /> : !data?.backups.length ? <Empty>No backups yet.</Empty> : (
        <Table head={["File", "Created", "Size", ""]}>{data.backups.map((b: Row) => (
          <tr key={b.name}><td>{b.name}</td><td>{fdt(b.at)}</td><td>{(b.size / 1024).toFixed(0)} KB</td>
            <td className="actions"><button className="btn sm" onClick={() => verify(b.name)}>Verify</button>
              {can("backup.restore") && <><button className="btn sm" onClick={() => download(`/backups/${b.name}/download`, b.name).catch((e) => toast(e.message, "err"))}>Download</button>
                <button className="btn sm danger" onClick={() => restore(b.name)}>Restore</button></>}</td></tr>))}</Table>)}
    </div>
  );
}

function Diag() {
  const { data, loading, reload } = useAsync(() => api("/diagnostics"), []);
  if (loading || !data) return <Loading />;
  return (
    <div>
      <div className="stats"><div className="stat"><div className="stat-label">Version</div><div className="stat-value">{data.version}</div></div>
        <div className="stat"><div className="stat-label">Database</div><div className="stat-value">{data.database}</div><small className="muted">{data.db_url}</small></div>
        <div className="stat"><div className="stat-label">Free disk</div><div className="stat-value">{data.disk_free_mb} MB</div></div>
        <div className="stat"><div className="stat-label">Last backup</div><div className="stat-value">{data.last_backup ? fdt(data.last_backup.at) : "never"}</div></div></div>
      <h3>Data integrity checks {data.healthy ? <Badge tone="ok">all passed</Badge> : <Badge tone="err">problems found</Badge>}</h3>
      <Table head={["Check", "Result", "Detail"]}>{data.checks.map((c: Row) => <tr key={c.name}><td>{c.name}</td><td>{c.ok ? <Badge tone="ok">OK</Badge> : <Badge tone="err">FAIL</Badge>}</td><td>{c.detail}</td></tr>)}</Table>
      <button className="btn" onClick={reload}>Re-run checks</button>
    </div>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const { data, loading } = useAsync(() => api("/audit", { params: { action } }), [action]);
  return (
    <div>
      <div className="filters"><select value={action} onChange={(e) => setAction(e.target.value)}><option value="">All actions</option>
        {["invoice.cancel", "invoice.reprint", "price.override", "stock.adjust", "sale.return", "user.", "backup.", "settings", "export.", "import.", "day.close", "login"].map((a) => <option key={a} value={a}>{a}</option>)}</select></div>
      {loading ? <Loading /> : !data?.length ? <Empty>No entries</Empty> : (
        <Table head={["When", "User", "Action", "Record", "Reason", "Details"]}>{data.map((a: Row) => (
          <tr key={a.id}><td>{fdt(a.at)}</td><td>{a.username}</td><td>{a.action}</td><td>{a.record_type} {a.record_id ?? ""}</td><td>{a.reason}</td>
            <td><small>{a.before && "before: " + JSON.stringify(a.before)}{a.after && " after: " + JSON.stringify(a.after)}</small></td></tr>))}</Table>)}
    </div>
  );
}
