import { useState } from "react";
import { api, fdate, inr, Row, toPaise, rupees } from "../api";
import { Badge, Empty, Field, Loading, Modal, Table, useAsync, useSession, useToast } from "../ui";

export default function Purchases() {
  const { can } = useSession();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<Row | null>(null);
  const { data, loading, error, reload } = useAsync(() => api("/purchases"), []);
  return (
    <div>
      <div className="page-head"><h2>Purchases</h2>{can("purchases.create") && <button className="btn primary" onClick={() => setOpen(true)}>+ New purchase</button>}</div>
      {loading ? <Loading /> : error ? <Empty>{error}</Empty> : !data?.length ? <Empty>No purchases yet. Receive goods from a supplier to increase stock.</Empty> : (
        <Table head={["No.", "Supplier inv.", "Date", "Supplier", "Total", "Paid", "Due"]}>
          {data.map((p: Row) => (
            <tr key={p.id}><td><button className="link" onClick={() => api("/purchases/" + p.id).then(setView)}>{p.number}</button></td><td>{p.supplier_invoice_no}</td><td>{fdate(p.date)}</td><td>{p.supplier}</td>
              <td className="r">{inr(p.total)}</td><td className="r">{inr(p.paid)}</td><td className="r">{p.due > 0 ? <Badge tone="warn">{inr(p.due)}</Badge> : "—"}</td></tr>
          ))}
        </Table>
      )}
      {open && <PurchaseForm onClose={(ch) => { setOpen(false); ch && reload(); }} />}
      {view && (
        <Modal title={`Purchase ${view.number}`} onClose={() => setView(null)} wide>
          <Table head={["Item", "Qty", "Cost", "GST%", "Taxable", "Tax", "Total"]}>
            {view.lines.map((l: Row, i: number) => (<tr key={i}><td>{l.name}</td><td>{l.qty}</td><td className="r">{inr(l.unit_cost)}</td><td>{l.gst_rate}</td><td className="r">{inr(l.taxable)}</td><td className="r">{inr(l.tax)}</td><td className="r">{inr(l.line_total)}</td></tr>))}
          </Table>
          <div className="row-between grand"><span>Total</span><span>{inr(view.total)}</span></div>
        </Modal>
      )}
    </div>
  );
}

type PL = { product: Row; qty: string; cost: string };

function PurchaseForm({ onClose }: { onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const { data: sups } = useAsync(() => api("/suppliers"), []);
  const [supplier, setSupplier] = useState("");
  const [invNo, setInvNo] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<PL[]>([]);
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Row[]>([]);
  const [method, setMethod] = useState("cash");
  const [paid, setPaid] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function search(v: string) { setQ(v); setRes(v.trim() ? await api("/products", { params: { q: v, limit: 6 } }) : []); }
  const add = (p: Row) => { setLines([...lines, { product: p, qty: "1", cost: rupees(p.purchase_price) }]); setQ(""); setRes([]); };
  const taxable = lines.reduce((s, l) => s + Math.round((parseFloat(l.qty) || 0) * toPaise(l.cost)), 0);
  const tax = lines.reduce((s, l) => s + Math.round(Math.round((parseFloat(l.qty) || 0) * toPaise(l.cost)) * l.product.gst_rate / 100), 0);
  async function save() {
    setErr(""); setBusy(true);
    try {
      await api("/purchases", { body: { supplier_id: Number(supplier), supplier_invoice_no: invNo, note,
        lines: lines.map((l) => ({ product_id: l.product.id, qty: parseFloat(l.qty), unit_cost: toPaise(l.cost) })),
        payments: toPaise(paid) > 0 ? [{ method, amount: toPaise(paid) }] : [] } });
      toast("Purchase saved, stock updated"); onClose(true);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <Modal title="New purchase (goods received)" onClose={() => onClose()} wide>
      <div className="grid3">
        <Field label="Supplier *"><select value={supplier} onChange={(e) => setSupplier(e.target.value)}><option value="">Select…</option>{sups?.map((s: Row) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label="Supplier invoice no. *"><input value={invNo} onChange={(e) => setInvNo(e.target.value)} /></Field>
        <Field label="Note"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      {sups && sups.length === 0 && <div className="banner warn">Add a supplier first (Suppliers menu).</div>}
      <div className="search-box"><input placeholder="Search product to add…" value={q} onChange={(e) => search(e.target.value)} />
        {res.length > 0 && <div className="dropdown">{res.map((p) => <button key={p.id} className="dd-item" onClick={() => add(p)}><span>{p.name}</span><small>{p.sku}</small></button>)}</div>}</div>
      <Table head={["Item", "Qty", "Cost ₹ (excl. GST)", "GST", ""]}>
        {lines.length === 0 && <tr><td colSpan={5}><div className="empty">No items yet</div></td></tr>}
        {lines.map((l, i) => (
          <tr key={i}><td>{l.product.name}</td>
            <td><input className="num" type="number" min="0" step="any" value={l.qty} onChange={(e) => setLines(lines.map((x, k) => k === i ? { ...x, qty: e.target.value } : x))} /></td>
            <td><input className="num" type="number" min="0" step="0.01" value={l.cost} onChange={(e) => setLines(lines.map((x, k) => k === i ? { ...x, cost: e.target.value } : x))} /></td>
            <td>{l.product.gst_rate}%</td><td><button className="btn ghost sm" onClick={() => setLines(lines.filter((_, k) => k !== i))}>✕</button></td></tr>
        ))}
      </Table>
      <div className="grid3">
        <div><div className="row-between"><span>Taxable</span><span>{inr(taxable)}</span></div><div className="row-between"><span>GST</span><span>{inr(tax)}</span></div><div className="row-between grand"><span>Total</span><span>{inr(taxable + tax)}</span></div></div>
        <Field label="Paid now ₹ (leave blank = on credit)"><input type="number" min="0" step="0.01" value={paid} onChange={(e) => setPaid(e.target.value)} /></Field>
        <Field label="Paid via"><select value={method} onChange={(e) => setMethod(e.target.value)}><option value="cash">Cash</option><option value="upi">UPI</option><option value="bank">Bank</option></select></Field>
      </div>
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Cancel</button><button className="btn primary" disabled={busy || !supplier || !invNo || !lines.length} onClick={save}>Save purchase</button></div>
    </Modal>
  );
}
