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
              <td className="r">{inr(p.total)}</td><td className="r">{inr(p.paid)}</td><td className="r">{p.status === "cancelled" ? <Badge tone="err">Cancelled</Badge> : p.due > 0 ? <Badge tone="warn">{inr(p.due)}</Badge> : "—"}</td></tr>
          ))}
        </Table>
      )}
      {open && <PurchaseForm onClose={(ch) => { setOpen(false); ch && reload(); }} />}
      {view && <PurchaseView p={view} can={can} onClose={(ch) => { setView(null); ch && reload(); }} />}
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

function PurchaseView({ p, can, onClose }: { p: Row; can: (x: string) => boolean; onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [mode, setMode] = useState<"" | "return" | "cancel">("");
  const [qty, setQty] = useState<Record<number, string>>({});
  const [method, setMethod] = useState("cash");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  async function go() {
    try {
      if (mode === "cancel") {
        await api(`/purchases/${p.id}/cancel`, { body: { reason } });
        toast("Purchase cancelled; stock and supplier balance reversed");
      } else {
        const lines = p.lines.filter((l: Row) => parseFloat(qty[l.id] || "0") > 0).map((l: Row) => ({ purchase_line_id: l.id, qty: parseFloat(qty[l.id]) }));
        if (!lines.length) return setErr("Enter a quantity to return");
        const r = await api(`/purchases/${p.id}/returns`, { body: { lines, refund_method: method, reason } });
        toast(`Return ${r.number}: payable reduced ${inr(r.payable_reduction)}, refund received ${inr(r.refund_amount)}`);
      }
      onClose(true);
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title={`Purchase ${p.number}${p.status === "cancelled" ? " — CANCELLED" : ""}`} onClose={() => onClose()} wide>
      <Table head={mode === "return" ? ["Item", "Bought", "Returned", "Return qty"] : ["Item", "Qty", "Cost", "GST%", "Taxable", "Tax", "Total"]}>
        {p.lines.map((l: Row, i: number) => mode === "return" ? (
          <tr key={i}><td>{l.name}</td><td>{l.qty}</td><td>{l.returned_qty}</td>
            <td><input className="num" type="number" min="0" max={l.qty - l.returned_qty} step="any" value={qty[l.id] || ""} disabled={l.qty - l.returned_qty <= 0} onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })} /></td></tr>
        ) : (
          <tr key={i}><td>{l.name}</td><td>{l.qty}{l.returned_qty ? <small className="muted"> ({l.returned_qty} returned)</small> : null}</td><td className="r">{inr(l.unit_cost)}</td><td>{l.gst_rate}</td><td className="r">{inr(l.taxable)}</td><td className="r">{inr(l.tax)}</td><td className="r">{inr(l.line_total)}</td></tr>
        ))}
      </Table>
      <div className="row-between grand"><span>Total {p.is_igst ? "(IGST)" : ""}</span><span>{inr(p.total)}</span></div>
      {p.status === "cancelled" && <div className="banner warn">Cancelled: {p.cancel_reason}</div>}
      {mode && (<div className="card">
        <h3>{mode === "cancel" ? "Cancel this purchase" : "Return goods to supplier"}</h3>
        {mode === "return" && <Field label="If nothing is payable, supplier refunds via"><select value={method} onChange={(e) => setMethod(e.target.value)}><option value="cash">Cash</option><option value="upi">UPI</option><option value="bank">Bank</option></select></Field>}
        <Field label="Reason (required)"><input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        {err && <div className="error">{err}</div>}
        <div className="actions end"><button className="btn" onClick={() => { setMode(""); setErr(""); }}>Back</button>
          <button className={"btn " + (mode === "cancel" ? "danger" : "primary")} disabled={reason.trim().length < 3} onClick={go}>{mode === "cancel" ? "Cancel purchase" : "Process return"}</button></div></div>)}
      {!mode && p.status === "posted" && <div className="actions end">
        {can("purchases.return") && <button className="btn" onClick={() => setMode("return")}>Return to supplier</button>}
        {can("purchases.cancel") && <button className="btn danger" onClick={() => setMode("cancel")}>Cancel purchase</button>}</div>}
    </Modal>
  );
}
