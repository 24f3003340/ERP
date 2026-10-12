import { FormEvent, useState } from "react";
import { api } from "../api";
import { Field } from "../ui";

export function AuthScreen({ mode, onDone }: { mode: "setup" | "login"; onDone: (token: string) => void }) {
  const [f, setF] = useState({ business_name: "", full_name: "", username: "", password: "", gstin: "", phone: "", address: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = mode === "setup" ? await api("/setup", { body: f }) : await api("/login", { body: { username: f.username, password: f.password } });
      onDone(r.token);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="center-screen">
      <form className="card auth" onSubmit={submit}>
        <h1>🧮 Local ERP</h1>
        <p className="muted">{mode === "setup" ? "First-time setup: create your business and the owner account." : "Sign in to continue. Works fully offline."}</p>
        {mode === "setup" && (<>
          <Field label="Business / shop name"><input required autoFocus value={f.business_name} onChange={set("business_name")} /></Field>
          <div className="grid2">
            <Field label="GSTIN (optional)"><input value={f.gstin} onChange={set("gstin")} /></Field>
            <Field label="Phone"><input value={f.phone} onChange={set("phone")} /></Field>
          </div>
          <Field label="Address"><input value={f.address} onChange={set("address")} /></Field>
          <Field label="Your name"><input value={f.full_name} onChange={set("full_name")} /></Field>
        </>)}
        <Field label="Username"><input required minLength={3} autoFocus={mode === "login"} value={f.username} onChange={set("username")} autoComplete="username" /></Field>
        <Field label="Password" hint={mode === "setup" ? "At least 8 characters" : undefined}>
          <input required type="password" minLength={mode === "setup" ? 8 : 1} value={f.password} onChange={set("password")} autoComplete={mode === "setup" ? "new-password" : "current-password"} />
        </Field>
        {err && <div className="error" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy}>{mode === "setup" ? "Create & start" : "Login"}</button>
      </form>
    </div>
  );
}
