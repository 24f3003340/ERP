import { useState } from "react";
import { api, fdt, inr, Row, toPaise, rupees } from "../api";
import { Badge, Empty, Field, Loading, Modal, Table, useAsync, useSession, useToast } from "../ui";

export default function Parties({ kind }: { kind: "customer" | "supplier" }) {
  const { can } = useSession();
  const toast = useToast();
  const base = kind === "customer" ? "/customers" : "/suppliers";
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<Row | null>(null);
  const [stmt, setStmt] = useState<Row | null>(null);
  const [pay, setPay] = useState<Row | null>(null);
  const { data, loading, error, reload } = useAsync(() => api(base, { params: { q } }), [kind, q]);
  const label = kind === "customer" ? "Customer" : "Supplier";
  return (
    <div>
      <div className="page-head"><h2>{label}s</h2>{can("parties.edit") && <button className="btn primary" onClick={() => setEdit({ name: "", phone: "", gstin: "", address: "", state_code: "", credit_limit: "0" })}>+ Add {label.toLowerCase()}</button>}</div>
      <div className="filters"><input placeholder="Search name / phone" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      {loading ? <Loading /> : error ? <Empty>{error}</Empty> : !data?.length ? <Empty>No {kind}s yet.</Empty> : (
        <Table head={["Name", "Phone", "GSTIN", kind === "customer" ? "Credit limit" : "", kind === "customer" ? "Receivable" : "Payable", ""]}>
          {data.map((c: Row) => (
            <tr key={c.id}><td>{c.name}</td><td>{c.phone}</td><td>{c.gstin}</td><td className="r">{kind === "customer" && c.credit_limit ? inr(c.credit_limit) : ""}</td>
              <td className="r">{c.balance ? <Badge tone="warn">{inr(c.balance)}</Badge> : "—"}</td>
              <td className="actions">
                <button className="btn sm" onClick={() => setStmt(c)}>Statement</button>
                {c.balance > 0 && can("payments.create") && <button className="btn sm primary" onClick={() => setPay(c)}>{kind === "customer" ? "Receive" : "Pay"}</button>}
                {can("parties.edit") && <button className="btn sm" onClick={() => setEdit({ ...c, credit_limit: rupees(c.credit_limit || 0) })}>Edit</button>}
              </td></tr>
          ))}
        </Table>
      )}
      {edit && <PartyForm kind={kind} p={edit} onClose={(ch) => { setEdit(null); ch && reload(); }} />}
      {stmt && <Statement kind={kind} p={stmt} onClose={() => setStmt(null)} />}
      {pay && <Settle kind={kind} p={pay} onClose={(ch) => { setPay(null); ch && (toast("Payment recorded"), reload()); }} />}
    </div>
  );
}

function PartyForm({ kind, p, onClose }: { kind: string; p: Row; onClose: (changed?: boolean) => void }) {
  const [f, setF] = useState<Row>(p); const [err, setErr] = useState("");
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  async function save() {
    const base = kind === "customer" ? "/customers" : "/suppliers";
    try { await api(p.id ? `${base}/${p.id}` : base, { method: p.id ? "PUT" : "POST", body: { name: f.name, phone: f.phone, gstin: f.gstin, state_code: f.state_code || "", address: f.address, credit_limit: toPaise(f.credit_limit) } }); onClose(true); } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title={p.id ? "Edit" : "Add"} onClose={() => onClose()}>
      <Field label="Name *"><input autoFocus value={f.name} onChange={set("name")} /></Field>
      <div className="grid2"><Field label="Phone"><input value={f.phone} onChange={set("phone")} /></Field><Field label="GSTIN"><input value={f.gstin} onChange={set("gstin")} /></Field></div>
      <Field label="Address"><input value={f.address} onChange={set("address")} /></Field>
      <Field label="State code (2 digits, e.g. 08 = Rajasthan)" hint="If different from your business state, bills use IGST"><input maxLength={2} value={f.state_code || ""} onChange={set("state_code")} /></Field>
      {kind === "customer" && <Field label="Credit limit ₹ (0 = no limit)"><input type="number" min="0" step="0.01" value={f.credit_limit} onChange={set("credit_limit")} /></Field>}
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Cancel</button><button className="btn primary" disabled={!f.name.trim()} onClick={save}>Save</button></div>
    </Modal>
  );
}

function Statement({ kind, p, onClose }: { kind: string; p: Row; onClose: () => void }) {
  const { data, loading } = useAsync(() => api(`/${kind}s/${p.id}/statement`), [p.id]);
  return (
    <Modal title={`Statement — ${p.name}`} onClose={onClose} wide>
      {loading ? <Loading /> : !data?.length ? <Empty>No transactions</Empty> : (
        <Table head={["Date", "Description", kind === "customer" ? "Billed" : "Purchased", "Paid / Credit", "Balance"]}>
          {data.map((r: Row, i: number) => (<tr key={i}><td>{fdt(r.at)}</td><td>{r.description}</td><td className="r">{r.debit ? inr(r.debit) : ""}</td><td className="r">{r.credit ? inr(r.credit) : ""}</td><td className="r">{inr(r.balance)}</td></tr>))}
        </Table>)}
      <div className="actions end"><button className="btn" onClick={() => window.print()}>🖨 Print</button></div>
    </Modal>
  );
}

function Settle({ kind, p, onClose }: { kind: string; p: Row; onClose: (changed?: boolean) => void }) {
  const [amount, setAmount] = useState(rupees(p.balance)); const [method, setMethod] = useState("cash"); const [err, setErr] = useState("");
  async function go() {
    try { await api(kind === "customer" ? `/customers/${p.id}/receipts` : `/suppliers/${p.id}/payments`, { body: { amount: toPaise(amount), method } }); onClose(true); } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title={(kind === "customer" ? "Receive from " : "Pay ") + p.name} onClose={() => onClose()}>
      <p>Outstanding: <b>{inr(p.balance)}</b>. Settled against the oldest invoices first.</p>
      <div className="grid2"><Field label="Amount ₹"><input autoFocus type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Method"><select value={method} onChange={(e) => setMethod(e.target.value)}><option value="cash">Cash</option><option value="upi">UPI</option><option value="bank">Bank</option><option value="card">Card</option></select></Field></div>
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Cancel</button><button className="btn primary" disabled={toPaise(amount) <= 0} onClick={go}>Record</button></div>
    </Modal>
  );
}
