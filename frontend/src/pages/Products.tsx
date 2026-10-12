import { ChangeEvent, useState } from "react";
import { api, download, inr, num, Row, rupees, toPaise } from "../api";
import { Badge, Empty, Field, Loading, Modal, Table, useAsync, useSession, useToast } from "../ui";

const blank = { sku: "", barcode: "", name: "", category: "", unit: "pcs", hsn: "", sale_price: "", purchase_price: "", gst_rate: "0", price_includes_tax: true, reorder_level: "0", opening_qty: "0", active: true };

export default function Products() {
  const { can } = useSession();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [low, setLow] = useState(false);
  const [edit, setEdit] = useState<Row | null>(null);
  const [adj, setAdj] = useState<Row | null>(null);
  const [ledger, setLedger] = useState<Row | null>(null);
  const [imp, setImp] = useState(false);
  const [count, setCount] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api("/products", { params: { q, low_stock: low || undefined, limit: 500 } }), [q, low]);
  return (
    <div>
      <div className="page-head">
        <h2>Products & Stock</h2>
        <div className="actions">
          {can("export.run") && <button className="btn" onClick={() => download("/products/export/csv", "products.csv").catch((e) => toast(e.message, "err"))}>⬇ Export CSV</button>}
          {can("import.run") && <button className="btn" onClick={() => setImp(true)}>⬆ Import CSV</button>}
          {can("stock.adjust") && <button className="btn" onClick={() => setCount(true)}>Stock count</button>}
          {can("products.edit") && <button className="btn primary" onClick={() => setEdit({ ...blank })}>+ Add product</button>}
        </div>
      </div>
      <div className="filters">
        <input placeholder="Search name / SKU / barcode" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Low stock only</label>
      </div>
      {loading ? <Loading /> : error ? <Empty>{error}</Empty> : !data?.length ? <Empty>No products yet. Add your first product or import a CSV.</Empty> : (
        <Table head={["SKU", "Name", "Category", "Price", "Cost", "GST", "Stock", ""]}>
          {data.map((p: Row) => (
            <tr key={p.id}>
              <td>{p.sku}{p.barcode && <small className="muted"><br />{p.barcode}</small>}</td><td>{p.name}</td><td>{p.category}</td>
              <td className="r">{inr(p.sale_price)}</td><td className="r">{inr(p.purchase_price)}</td><td>{p.gst_rate}%</td>
              <td><Badge tone={p.stock_qty <= 0 ? "err" : p.stock_qty <= p.reorder_level ? "warn" : "ok"}>{num(p.stock_qty)} {p.unit}</Badge></td>
              <td className="actions">
                <button className="btn sm" onClick={() => setLedger(p)}>Ledger</button>
                {can("stock.adjust") && <button className="btn sm" onClick={() => setAdj(p)}>Adjust</button>}
                {can("products.edit") && <button className="btn sm" onClick={() => setEdit({ ...p, sale_price: rupees(p.sale_price), purchase_price: rupees(p.purchase_price), barcode: p.barcode || "" })}>Edit</button>}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {edit && <ProductForm p={edit} onClose={(ch) => { setEdit(null); ch && reload(); }} />}
      {adj && <AdjustDlg p={adj} onClose={(ch) => { setAdj(null); ch && reload(); }} />}
      {ledger && <LedgerDlg p={ledger} onClose={() => setLedger(null)} />}
      {imp && <ImportDlg onClose={(ch) => { setImp(false); ch && reload(); }} />}
      {count && <CountDlg products={data || []} onClose={(ch) => { setCount(false); ch && reload(); }} />}
    </div>
  );
}

function ProductForm({ p, onClose }: { p: Row; onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [f, setF] = useState<Row>(p);
  const [err, setErr] = useState("");
  const isNew = !p.id;
  const set = (k: string) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });
  async function save() {
    const body = { sku: f.sku, barcode: f.barcode || null, name: f.name, category: f.category, unit: f.unit, hsn: f.hsn, sale_price: toPaise(f.sale_price),
      purchase_price: toPaise(f.purchase_price), gst_rate: parseFloat(f.gst_rate) || 0, price_includes_tax: f.price_includes_tax,
      reorder_level: parseFloat(f.reorder_level) || 0, opening_qty: parseFloat(f.opening_qty) || 0, active: f.active };
    try { await api(isNew ? "/products" : "/products/" + p.id, { method: isNew ? "POST" : "PUT", body }); toast("Product saved"); onClose(true); } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title={isNew ? "Add product" : "Edit product"} onClose={() => onClose()} wide>
      <div className="grid3">
        <Field label="Name *"><input autoFocus value={f.name} onChange={set("name")} /></Field>
        <Field label="SKU *"><input value={f.sku} onChange={set("sku")} /></Field>
        <Field label="Barcode"><input value={f.barcode} onChange={set("barcode")} /></Field>
        <Field label="Category"><input value={f.category} onChange={set("category")} /></Field>
        <Field label="Unit"><input value={f.unit} onChange={set("unit")} /></Field>
        <Field label="HSN code"><input value={f.hsn} onChange={set("hsn")} /></Field>
        <Field label="Sale price ₹ *"><input type="number" step="0.01" min="0" value={f.sale_price} onChange={set("sale_price")} /></Field>
        <Field label="Purchase price ₹"><input type="number" step="0.01" min="0" value={f.purchase_price} onChange={set("purchase_price")} /></Field>
        <Field label="GST %" hint="Use the rate approved by your CA"><select value={f.gst_rate} onChange={set("gst_rate")}>{["0", "0.25", "3", "5", "12", "18", "28"].map((r) => <option key={r} value={r}>{r}%</option>)}</select></Field>
        <Field label="Sale price includes GST?"><select value={f.price_includes_tax ? "1" : "0"} onChange={(e) => setF({ ...f, price_includes_tax: e.target.value === "1" })}><option value="1">Yes (MRP)</option><option value="0">No (add GST on top)</option></select></Field>
        <Field label="Reorder level"><input type="number" min="0" step="any" value={f.reorder_level} onChange={set("reorder_level")} /></Field>
        {isNew ? <Field label="Opening stock" hint="Creates an auditable opening movement"><input type="number" min="0" step="any" value={f.opening_qty} onChange={set("opening_qty")} /></Field>
          : <Field label="Active"><select value={f.active ? "1" : "0"} onChange={(e) => setF({ ...f, active: e.target.value === "1" })}><option value="1">Active</option><option value="0">Inactive</option></select></Field>}
      </div>
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Cancel</button><button className="btn primary" onClick={save}>Save</button></div>
    </Modal>
  );
}

function AdjustDlg({ p, onClose }: { p: Row; onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [d, setD] = useState(""); const [reason, setReason] = useState(""); const [err, setErr] = useState("");
  async function go() { try { await api("/stock/adjust", { body: { product_id: p.id, qty_delta: parseFloat(d), reason } }); toast("Stock adjusted"); onClose(true); } catch (e: any) { setErr(e.message); } }
  return (
    <Modal title={`Adjust stock — ${p.name}`} onClose={() => onClose()}>
      <p>Current stock: <b>{num(p.stock_qty)} {p.unit}</b>. Use a negative number to reduce (damage, loss).</p>
      <Field label="Change (+/−)"><input autoFocus type="number" step="any" value={d} onChange={(e) => setD(e.target.value)} /></Field>
      <Field label="Reason (required)"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Cancel</button><button className="btn primary" disabled={!parseFloat(d) || reason.trim().length < 3} onClick={go}>Apply</button></div>
    </Modal>
  );
}

function LedgerDlg({ p, onClose }: { p: Row; onClose: () => void }) {
  const { data, loading } = useAsync(() => api(`/products/${p.id}/ledger`), [p.id]);
  return (
    <Modal title={`Stock ledger — ${p.name}`} onClose={onClose} wide>
      {loading ? <Loading /> : !data?.length ? <Empty>No movements</Empty> : (
        <Table head={["When", "Type", "Ref", "Change", "Note"]}>
          {data.map((m: Row) => (<tr key={m.id}><td>{new Date(m.at).toLocaleString("en-IN")}</td><td>{m.source_type}</td><td>{m.source_id}</td>
            <td className={"r " + (m.qty_delta < 0 ? "neg" : "pos")}>{m.qty_delta > 0 ? "+" : ""}{num(m.qty_delta)}</td><td>{m.note}</td></tr>))}
        </Table>)}
    </Modal>
  );
}

function ImportDlg({ onClose }: { onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<Row | null>(null);
  const [err, setErr] = useState("");
  async function run(commit: boolean) {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file); setErr("");
    try { const r = await api("/products/import", { form: fd, params: { commit: commit ? "true" : undefined } }); setRes(r); if (commit) { toast(`Imported ${r.imported} products`); onClose(true); } } catch (e: any) { setErr(e.message); }
  }
  return (
    <Modal title="Import products from CSV" onClose={() => onClose()}>
      <p className="muted">Columns: <code>sku, name, sale_price</code> (required) + <code>barcode, category, unit, hsn, purchase_price, gst_rate, price_includes_tax, reorder_level, opening_qty</code>. Prices in rupees. The import is all-or-nothing.</p>
      <a className="link" href={"data:text/csv;charset=utf-8," + encodeURIComponent("sku,name,sale_price,purchase_price,gst_rate,category,unit,barcode,reorder_level,opening_qty\nSKU001,Sample item,105.00,80.00,5,Grocery,pcs,8901234567890,5,20\n")} download="products_template.csv">Download template</a>
      <input type="file" accept=".csv" onChange={(e) => { setFile(e.target.files?.[0] || null); setRes(null); }} />
      {res && (<div className="card"><b>{res.rows} valid rows</b>{res.errors.length ? <ul className="errlist">{res.errors.slice(0, 20).map((e: Row, i: number) => <li key={i}>{e.row ? "Row " + e.row + ": " : ""}{e.error}</li>)}</ul> : <div className="pos">No errors — ready to import.</div>}</div>)}
      {err && <div className="error">{err}</div>}
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Close</button><button className="btn" disabled={!file} onClick={() => run(false)}>Preview</button>
        <button className="btn primary" disabled={!file || !res || res.errors.length > 0} onClick={() => run(true)}>Import</button></div>
    </Modal>
  );
}

function CountDlg({ products, onClose }: { products: Row[]; onClose: (changed?: boolean) => void }) {
  const toast = useToast();
  const [counted, setCounted] = useState<Record<number, string>>({});
  const [res, setRes] = useState<Row[] | null>(null);
  const items = () => products.filter((p) => counted[p.id] !== undefined && counted[p.id] !== "").map((p) => ({ product_id: p.id, counted: parseFloat(counted[p.id]) }));
  async function run(apply: boolean) {
    try { const r = await api("/stock/count", { body: { items: items(), apply } }); setRes(r); if (apply) { toast("Stock updated to counted quantities"); onClose(true); } } catch (e: any) { toast(e.message, "err"); }
  }
  return (
    <Modal title="Physical stock count" onClose={() => onClose()} wide>
      <p className="muted">Enter counted quantities for the items you counted, preview the variance report, then apply.</p>
      <Table head={["Item", "System", "Counted", "Variance"]}>
        {products.map((p) => { const v = res?.find((r) => r.product_id === p.id); return (
          <tr key={p.id}><td>{p.name}</td><td>{num(p.stock_qty)}</td>
            <td><input className="num" type="number" min="0" step="any" value={counted[p.id] ?? ""} onChange={(e) => setCounted({ ...counted, [p.id]: e.target.value })} /></td>
            <td className={v && v.variance !== 0 ? (v.variance < 0 ? "neg" : "pos") : ""}>{v ? `${num(v.variance)} (${inr(v.value_variance)})` : ""}</td></tr>); })}
      </Table>
      <div className="actions end"><button className="btn" onClick={() => onClose()}>Close</button><button className="btn" disabled={!items().length} onClick={() => run(false)}>Preview variance</button>
        <button className="btn primary" disabled={!res} onClick={() => run(true)}>Apply adjustments</button></div>
    </Modal>
  );
}
