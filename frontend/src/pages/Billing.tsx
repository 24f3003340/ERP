import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, calcLine, inr, num, Row, toPaise, rupees } from "../api";
import { Badge, Field, Modal, useSession, useToast } from "../ui";
import { t } from "../i18n";
import { InvoiceView } from "./InvoicePrint";

type CartLine = { product: Row; qty: number; price: number; discount: number };
type Pay = { method: string; amount: string };

const HOLD_KEY = "erp_held_bills";
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());

export default function Billing() {
  const { can } = useSession();
  const toast = useToast();
  const [cart, setCart] = useState<CartLine[]>([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Row[]>([]);
  const [customers, setCustomers] = useState<Row[]>([]);
  const [customerId, setCustomerId] = useState<number | "">("");
  const [pays, setPays] = useState<Pay[]>([{ method: "cash", amount: "" }]);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<Row | null>(null);
  const [err, setErr] = useState("");
  const [held, setHeld] = useState<Row[]>(() => { try { return JSON.parse(localStorage.getItem(HOLD_KEY) || "[]"); } catch { return []; } });
  const [showHeld, setShowHeld] = useState(false);
  const idem = useRef(newKey());
  const searchRef = useRef<HTMLInputElement>(null);
  const canPrice = can("price.override");

  useEffect(() => { api("/customers").then(setCustomers).catch(() => {}); }, []);
  useEffect(() => {
    if (!q.trim()) return setResults([]);
    const h = setTimeout(() => api("/products", { params: { q, limit: 8 } }).then(setResults).catch(() => {}), 120);
    return () => clearTimeout(h);
  }, [q]);

  const add = useCallback((p: Row) => {
    setCart((c) => {
      const i = c.findIndex((l) => l.product.id === p.id);
      if (i >= 0) return c.map((l, k) => (k === i ? { ...l, qty: l.qty + 1 } : l));
      return [...c, { product: p, qty: 1, price: p.sale_price, discount: 0 }];
    });
    setQ(""); setResults([]); setErr("");
    searchRef.current?.focus();
  }, []);

  async function onSearchKey(e: React.KeyboardEvent) {
    if (e.key !== "Enter" || !q.trim()) return;
    e.preventDefault();
    const code = q.trim(), first = results[0];
    setQ(""); setResults([]);  // clear immediately so rapid scanner input is never lost
    try {
      add(await api("/products/lookup", { params: { code } }));
    } catch {
      if (first) add(first); else toast("Product not found: " + code, "err");
    }
  }

  const totals = useMemo(() => {
    let taxable = 0, tax = 0, disc = 0;
    cart.forEach((l) => {
      const c = calcLine(l.qty, l.price, l.discount, l.product.gst_rate, l.product.price_includes_tax);
      taxable += c.taxable; tax += c.tax; disc += l.discount;
    });
    const raw = taxable + tax, total = Math.round(raw / 100) * 100;
    return { taxable, tax, disc, total, round: total - raw };
  }, [cart]);
  const paid = pays.reduce((s, p) => s + toPaise(p.amount), 0);
  const due = totals.total - paid;

  const upd = (i: number, patch: Partial<CartLine>) => setCart((c) => c.map((l, k) => (k === i ? { ...l, ...patch } : l)));

  function payFull(method: string) { setPays([{ method, amount: rupees(totals.total) }]); }

  async function save() {
    setErr("");
    if (!cart.length) return setErr("Add at least one item");
    if (due < 0) return setErr("Payment is more than the bill total");
    if (due > 0 && !customerId) return setErr("Select a customer for credit sale or part payment (or collect the full amount)");
    setSaving(true);
    try {
      const inv = await api("/sales", {
        body: {
          customer_id: customerId || null, idem_key: idem.current,
          lines: cart.map((l) => ({ product_id: l.product.id, qty: l.qty, unit_price: l.price !== l.product.sale_price ? l.price : undefined, discount: l.discount })),
          payments: pays.filter((p) => toPaise(p.amount) > 0).map((p) => ({ method: p.method, amount: toPaise(p.amount) })),
        },
      });
      setDone(inv);
      toast(`Saved ${inv.number}`);
      setCart([]); setPays([{ method: "cash", amount: "" }]); setCustomerId("");
      idem.current = newKey();
    } catch (e: any) { setErr(e.message); } finally { setSaving(false); }
  }

  function hold() {
    if (!cart.length) return;
    const h = [...held, { at: Date.now(), cart, customerId }];
    setHeld(h); localStorage.setItem(HOLD_KEY, JSON.stringify(h));
    setCart([]); setCustomerId(""); toast("Bill put on hold");
  }
  function recall(i: number) {
    const h = held[i];
    setCart(h.cart); setCustomerId(h.customerId);
    const rest = held.filter((_, k) => k !== i);
    setHeld(rest); localStorage.setItem(HOLD_KEY, JSON.stringify(rest)); setShowHeld(false);
  }

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "F2") { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === "F9") { e.preventDefault(); if (!saving) save(); }
      if (e.key === "F8") { e.preventDefault(); hold(); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  return (
    <div className="billing">
      <div className="bill-main">
        <div className="page-head">
          <h2>{t("billing")}</h2>
          <div className="actions">
            <button className="btn" onClick={() => setShowHeld(true)}>Held bills ({held.length})</button>
            <button className="btn" onClick={hold} disabled={!cart.length}>Hold (F8)</button>
          </div>
        </div>
        <div className="search-box">
          <input ref={searchRef} autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onSearchKey}
            placeholder={t("search") + "  (F2)"} aria-label="Search product" />
          {results.length > 0 && (
            <div className="dropdown">
              {results.map((p) => (
                <button key={p.id} className="dd-item" onClick={() => add(p)}>
                  <span>{p.name} <small className="muted">{p.sku}{p.barcode ? " · " + p.barcode : ""}</small></span>
                  <span>{inr(p.sale_price)} <Badge tone={p.stock_qty <= 0 ? "err" : p.stock_qty <= p.reorder_level ? "warn" : "ok"}>{num(p.stock_qty)} {p.unit}</Badge></span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Item</th><th>Stock</th><th>Qty</th><th>Price</th><th>Disc ₹</th><th>GST</th><th className="r">Total</th><th></th></tr></thead>
            <tbody>
              {cart.length === 0 && <tr><td colSpan={9}><div className="empty">Scan a barcode or search to add items. Press Enter to add the first match.</div></td></tr>}
              {cart.map((l, i) => {
                const c = calcLine(l.qty, l.price, l.discount, l.product.gst_rate, l.product.price_includes_tax);
                const short = l.qty > l.product.stock_qty;
                return (
                  <tr key={l.product.id}>
                    <td>{i + 1}</td><td>{l.product.name}</td>
                    <td><Badge tone={short ? "err" : "muted"}>{num(l.product.stock_qty)}</Badge></td>
                    <td><input className="num" type="number" min="0.001" step="any" value={l.qty} onChange={(e) => upd(i, { qty: parseFloat(e.target.value) || 0 })} /></td>
                    <td>{canPrice ? <input className="num" type="number" step="0.01" value={rupees(l.price)} onChange={(e) => upd(i, { price: toPaise(e.target.value) })} /> : inr(l.price)}</td>
                    <td><input className="num" type="number" min="0" step="0.01" value={l.discount ? rupees(l.discount) : ""} placeholder="0" onChange={(e) => upd(i, { discount: toPaise(e.target.value) })} /></td>
                    <td>{l.product.gst_rate}%</td><td className="r">{inr(c.total)}</td>
                    <td><button className="btn ghost sm" onClick={() => setCart(cart.filter((_, k) => k !== i))} aria-label="Remove line">✕</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <aside className="bill-side card">
        <Field label="Customer (optional for walk-in)">
          <select value={customerId} onChange={(e) => setCustomerId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Walk-in customer</option>
            {customers.map((c) => (<option key={c.id} value={c.id}>{c.name}{c.phone ? " · " + c.phone : ""}{c.balance ? ` (due ${inr(c.balance)})` : ""}</option>))}
          </select>
        </Field>
        <div className="sum">
          <div className="row-between"><span>Taxable</span><span>{inr(totals.taxable)}</span></div>
          <div className="row-between"><span>GST</span><span>{inr(totals.tax)}</span></div>
          {totals.disc > 0 && <div className="row-between"><span>Discount given</span><span>{inr(totals.disc)}</span></div>}
          {totals.round !== 0 && <div className="row-between"><span>Round off</span><span>{inr(totals.round)}</span></div>}
          <div className="row-between grand"><span>{t("total")}</span><span>{inr(totals.total)}</span></div>
        </div>
        <div className="quick">
          <button className="btn" onClick={() => payFull("cash")} disabled={!cart.length}>Cash full</button>
          <button className="btn" onClick={() => payFull("upi")} disabled={!cart.length}>UPI full</button>
          <button className="btn" onClick={() => payFull("card")} disabled={!cart.length}>Card full</button>
        </div>
        {pays.map((p, i) => (
          <div key={i} className="pay-row">
            <select value={p.method} onChange={(e) => setPays(pays.map((x, k) => (k === i ? { ...x, method: e.target.value } : x)))}>
              <option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option><option value="bank">Bank</option>
            </select>
            <input className="num" type="number" min="0" step="0.01" placeholder="Amount ₹" value={p.amount}
              onChange={(e) => setPays(pays.map((x, k) => (k === i ? { ...x, amount: e.target.value } : x)))} />
            {pays.length > 1 && <button className="btn ghost sm" onClick={() => setPays(pays.filter((_, k) => k !== i))}>✕</button>}
          </div>
        ))}
        <button className="btn ghost sm" onClick={() => setPays([...pays, { method: "upi", amount: "" }])}>+ Split payment</button>
        <div className="row-between"><span>Paid</span><b>{inr(paid)}</b></div>
        <div className="row-between"><span>{due >= 0 ? "Balance (credit)" : "Excess"}</span><b className={due !== 0 ? "warn-text" : ""}>{inr(Math.abs(due))}</b></div>
        {err && <div className="error" role="alert">{err}</div>}
        <button className="btn primary big" disabled={saving || !cart.length} onClick={save}>{saving ? "Saving…" : "Save & Print (F9)"}</button>
      </aside>
      {done && <InvoiceView inv={done} onClose={() => { setDone(null); searchRef.current?.focus(); }} />}
      {showHeld && (
        <Modal title="Held bills" onClose={() => setShowHeld(false)}>
          {held.length === 0 ? <div className="empty">No held bills</div> : held.map((h, i) => (
            <div key={i} className="row-between"><span>{new Date(h.at).toLocaleTimeString()} · {h.cart.length} items</span><button className="btn" onClick={() => recall(i)}>Recall</button></div>
          ))}
        </Modal>
      )}
    </div>
  );
}
