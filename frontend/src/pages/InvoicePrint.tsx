import { useState } from "react";
import { api, fdt, inr, num, Row } from "../api";
import { Modal, useSession, useToast } from "../ui";

/** Printable invoice (A4 or 80mm thermal). Uses the browser print dialog, which also offers "Save as PDF". */
export function InvoiceView({ inv, onClose }: { inv: Row; onClose: () => void }) {
  const { business } = useSession();
  const toast = useToast();
  const [paper, setPaper] = useState(localStorage.getItem("erp_paper") || "a4");
  const cgstsgst = (tax: number) => [Math.floor(tax / 2), tax - Math.floor(tax / 2)];
  async function print() {
    localStorage.setItem("erp_paper", paper);
    try { await api(`/sales/${inv.id}/printed`, { method: "POST" }); } catch {}
    window.print();
  }
  const reprint = inv.print_count > 0;
  return (
    <Modal title={`Invoice ${inv.number}`} onClose={onClose} wide>
      <div className="no-print row-between" style={{ marginBottom: 8 }}>
        <div className="actions">
          <select value={paper} onChange={(e) => setPaper(e.target.value)} aria-label="Paper size">
            <option value="a4">A4</option><option value="thermal">Thermal 80mm</option>
          </select>
          <button className="btn primary" onClick={print}>🖨 Print / Save PDF</button>
          <button className="btn" onClick={() => toast("Invoice is saved. Use Print → Save as PDF to export.")}>ℹ️ Printer problem?</button>
        </div>
        {reprint && <span className="badge warn">Printed {inv.print_count}×</span>}
      </div>
      <div className={"print-area " + paper}>
        <div className="inv-head">
          <h2>{business.name}</h2>
          {business.address && <div>{business.address}</div>}
          <div>{[business.phone && "Ph: " + business.phone, business.gstin && "GSTIN: " + business.gstin].filter(Boolean).join(" | ")}</div>
          <div className="inv-title">{business.gstin ? "TAX INVOICE" : "INVOICE"}{inv.status === "cancelled" ? " — CANCELLED" : ""}{reprint ? " (DUPLICATE COPY)" : ""}</div>
        </div>
        <div className="row-between"><span>No: <b>{inv.number}</b></span><span>{fdt(inv.created_at)}</span></div>
        <div>Customer: {inv.customer}</div>
        <table className="inv-table">
          <thead><tr><th>#</th><th>Item</th><th>Qty</th><th>Rate</th><th>Disc</th><th>GST%</th><th className="r">Amount</th></tr></thead>
          <tbody>
            {inv.lines.map((l: Row, i: number) => (
              <tr key={l.id}><td>{i + 1}</td><td>{l.name}</td><td>{num(l.qty)} {l.unit}</td><td>{inr(l.unit_price)}</td>
                <td>{l.discount ? inr(l.discount) : ""}</td><td>{l.gst_rate}</td><td className="r">{inr(l.line_total)}</td></tr>
            ))}
          </tbody>
        </table>
        <div className="inv-totals">
          <div className="row-between"><span>Taxable value</span><span>{inr(inv.taxable)}</span></div>
          {inv.is_igst ? <div className="row-between"><span>IGST</span><span>{inr(inv.tax_total)}</span></div> : <>
            <div className="row-between"><span>CGST</span><span>{inr(cgstsgst(inv.tax_total)[0])}</span></div>
            <div className="row-between"><span>SGST</span><span>{inr(cgstsgst(inv.tax_total)[1])}</span></div></>}
          {inv.round_off !== 0 && <div className="row-between"><span>Round off</span><span>{inr(inv.round_off)}</span></div>}
          <div className="row-between grand"><span>Total</span><span>{inr(inv.total)}</span></div>
          <div className="row-between"><span>Paid</span><span>{inr(inv.paid)}</span></div>
          {inv.due > 0 && <div className="row-between"><span>Balance due</span><span>{inr(inv.due)}</span></div>}
        </div>
        <div className="inv-foot">{business.footer}</div>
      </div>
    </Modal>
  );
}
