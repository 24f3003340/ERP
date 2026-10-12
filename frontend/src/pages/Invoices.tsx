import { useState } from "react";
import { api, fdate, inr, num, Row, toPaise } from "../api";
import { Badge, Empty, Field, Loading, Modal, Table, useAsync, useSession, useToast } from "../ui";
import { InvoiceView } from "./InvoicePrint";

export default function Invoices() {
  const { can } = useSession();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState<Row | null>(null);
  const [mode, setMode] = useState<"view" | "return" | "cancel" | null>(null);
  const { data, loading, error, reload } = useAsync(() => api("/sales", { params: { q, status, date_from: from, date_to: to } }), [q, status, from, to]);

  async function openInv(id: number, m: "view" | "return" | "cancel") {
    try { setOpen(await api("/sales/" + id)); setMode(m); } catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <div>
      <div className="page-head"><h2>Invoices</h2></div>
      <div className="filters">
        <input placeholder="Search invoice no." value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option value="posted">Posted</option><option value="cancelled">Cancelled</option></select>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
      </div>
      {loading ? <Loading /> : error ? <Empty>{error}</Empty> : !data?.length ? <Empty>No invoices found.</Empty> : (
        <Table head={["Invoice", "Date", "Customer", "Total", "Paid", "Due", "Status", ""]}>
          {data.map((i: Row) => (
            <tr key={i.id}>
              <td><button className="link" onClick={() => openInv(i.id, "view")}>{i.number}</button></td>
              <td>{fdate(i.date)}</td><td>{i.customer}</td><td className="r">{inr(i.total)}</td><td className="r">{inr(i.paid)}</td>
              <td className="r">{i.due > 0 ? <Badge tone="warn">{inr(i.due)}</Badge> : "—"}</td>
              <td>{i.status === "cancelled" ? <Badge tone="err">Cancelled</Badge> : <Badge tone="ok">Posted</Badge>}</td>
              <td className="actions">
                {i.status === "posted" && can("sales.return") && <button className="btn sm" onClick={() => openInv(i.id, "return")}>Return</button>}
                {i.status === "posted" && can("sales.cancel") && <button className="btn sm danger" onClick={() => openInv(i.id, "cancel")}>Cancel</button>}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {open && mode === "view" && <InvoiceView inv={open} onClose={() => { setOpen(null); reload(); }} />}
      {open && mode === "cancel" && <CancelDlg inv={open} onClose={(ch) => { setOpen(null); ch && reload(); }} />}
      {open && mode === "return" && <ReturnDlg inv={open} onClose={(ch) => { setOpen(null); ch && reload(); }} />}
    </div>
  );
}

function CancelDlg({ inv, onClose }: { inv: Row; onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  async function go() {
    try { await api(`/sales/${inv.id}/cancel`, { body: { reason } }); toast("Invoice cancelled; stock and accounts reversed"); onClose(true); } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title={`Cancel ${inv.number}`} onClose={() => onClose()}>
      <p>The invoice stays on record as <b>cancelled</b>. Stock is restored, accounting entries are reversed and any payment is refunded. This is logged in the audit trail.</p>
      <Field label="Reason (required)"><input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Keep invoice</button><button className="btn danger" disabled={reason.trim().length < 3} onClick={go}>Cancel invoice</button></div>
    </Modal>
  );
}

function ReturnDlg({ inv, onClose }: { inv: Row; onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [qty, setQty] = useState<Record<number, string>>({});
  const [disp, setDisp] = useState<Record<number, string>>({});
  const [method, setMethod] = useState("cash");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  async function go() {
    const lines = inv.lines.filter((l: Row) => parseFloat(qty[l.id] || "0") > 0)
      .map((l: Row) => ({ sales_line_id: l.id, qty: parseFloat(qty[l.id]), disposition: disp[l.id] || "restock" }));
    if (!lines.length) return setErr("Enter a quantity to return");
    try {
      const r = await api(`/sales/${inv.id}/returns`, { body: { lines, refund_method: method, reason } });
      toast(`Return ${r.number}: ${r.due_reduction ? "due reduced " + inr(r.due_reduction) + "; " : ""}refund ${inr(r.refund_amount)}`);
      onClose(true);
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title={`Return against ${inv.number}`} onClose={() => onClose()} wide>
      <Table head={["Item", "Sold", "Returned", "Return qty", "Condition"]}>
        {inv.lines.map((l: Row) => (
          <tr key={l.id}><td>{l.name}</td><td>{num(l.qty)}</td><td>{num(l.returned_qty)}</td>
            <td><input className="num" type="number" min="0" max={l.qty - l.returned_qty} step="any" value={qty[l.id] || ""} disabled={l.qty - l.returned_qty <= 0}
              onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })} /></td>
            <td><select value={disp[l.id] || "restock"} onChange={(e) => setDisp({ ...disp, [l.id]: e.target.value })}>
              <option value="restock">Good — restock</option><option value="damaged">Damaged — no restock</option></select></td></tr>
        ))}
      </Table>
      <div className="grid2">
        <Field label="Refund via (if no dues to adjust)"><select value={method} onChange={(e) => setMethod(e.target.value)}><option value="cash">Cash</option><option value="upi">UPI</option><option value="bank">Bank</option><option value="card">Card</option></select></Field>
        <Field label="Reason (required)"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Close</button><button className="btn primary" disabled={reason.trim().length < 3} onClick={go}>Process return</button></div>
    </Modal>
  );
}
