import { useState } from "react";
import { api, download, fdate, inr, num, Row } from "../api";
import { Badge, Empty, Loading, Stat, Table, useAsync, useSession, useToast } from "../ui";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

export default function Reports() {
  const { can } = useSession();
  const toast = useToast();
  const [tab, setTab] = useState("sales");
  const [from, setFrom] = useState(monthStart()); const [to, setTo] = useState(today());
  const tabs: [string, string][] = [["sales", "Sales"], ["margin", "Product margin"], ["stock", "Stock valuation"], ["dues", "Receivables / Payables"], ["gst", "GST summary"]];
  const dated = ["sales", "margin", "gst"].includes(tab);
  const { data, loading, error } = useAsync(() => api(`/reports/${tab}`, { params: dated ? { date_from: from, date_to: to } : undefined }), [tab, from, to]);
  return (
    <div>
      <div className="page-head"><h2>Reports</h2>
        <div className="actions">{can("export.run") && <>
          <button className="btn" onClick={() => download("/reports/export/sales", "sales.csv", { date_from: from, date_to: to }).catch((e) => toast(e.message, "err"))}>⬇ Sales CSV</button>
          <button className="btn" onClick={() => download("/reports/export/purchases", "purchases.csv", { date_from: from, date_to: to }).catch((e) => toast(e.message, "err"))}>⬇ Purchases CSV</button></>}
          <button className="btn" onClick={() => window.print()}>🖨 Print</button></div></div>
      <div className="tabs">{tabs.map(([k, l]) => <button key={k} className={"tab" + (tab === k ? " active" : "")} onClick={() => setTab(k)}>{l}</button>)}</div>
      {dated && <div className="filters"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>}
      {loading ? <Loading /> : error || !data ? <Empty>{error}</Empty> : <Body tab={tab} d={data} />}
    </div>
  );
}

function Body({ tab, d }: { tab: string; d: Row }) {
  if (tab === "sales") return (<>
    <div className="stats"><Stat label="Sales (incl. GST)" value={inr(d.total)} tone="blue" /><Stat label="Bills" value={d.bills} /><Stat label="Returns" value={inr(d.returns)} />
      {Object.entries(d.by_method as Row).map(([m, a]) => <Stat key={m} label={`Collected ${m}`} value={inr(a as number)} />)}</div>
    {d.days.length ? <Table head={["Date", "Bills", "Taxable", "GST", "Total"]}>{d.days.map((r: Row) => <tr key={r.date}><td>{fdate(r.date)}</td><td>{r.bills}</td><td className="r">{inr(r.taxable)}</td><td className="r">{inr(r.tax)}</td><td className="r">{inr(r.total)}</td></tr>)}</Table> : <Empty>No sales in this period.</Empty>}</>);
  if (tab === "margin") return d.rows.length ? <Table head={["Product", "Qty sold", "Revenue (ex-GST)", "Cost", "Margin", "%"]}>{d.rows.map((r: Row) => <tr key={r.product_id}><td>{r.name}</td><td>{num(r.qty)}</td><td className="r">{inr(r.revenue)}</td><td className="r">{inr(r.cost)}</td><td className="r">{inr(r.margin)}</td><td>{r.margin_pct}%</td></tr>)}</Table> : <Empty>No sales in this period.</Empty>;
  if (tab === "stock") return (<><div className="stats"><Stat label="Stock value (at cost)" value={inr(d.total_value)} tone="blue" /></div>
    <Table head={["SKU", "Item", "Stock", "Cost", "Value", ""]}>{d.rows.map((r: Row) => <tr key={r.id}><td>{r.sku}</td><td>{r.name}</td><td>{num(r.stock)} {r.unit}</td><td className="r">{inr(r.cost)}</td><td className="r">{inr(r.value)}</td><td>{r.low && <Badge tone="warn">Low</Badge>}</td></tr>)}</Table></>);
  if (tab === "dues") return (<div className="grid2 gap">
    <div><h3>Receivable from customers — {inr(d.total_receivable)}</h3>{d.receivables.length ? <Table head={["Customer", "Phone", "Due"]}>{d.receivables.map((r: Row) => <tr key={r.id}><td>{r.name}</td><td>{r.phone}</td><td className="r">{inr(r.balance)}</td></tr>)}</Table> : <Empty>Nothing receivable.</Empty>}</div>
    <div><h3>Payable to suppliers — {inr(d.total_payable)}</h3>{d.payables.length ? <Table head={["Supplier", "Phone", "Due"]}>{d.payables.map((r: Row) => <tr key={r.id}><td>{r.name}</td><td>{r.phone}</td><td className="r">{inr(r.balance)}</td></tr>)}</Table> : <Empty>Nothing payable.</Empty>}</div></div>);
  return (<>
    <div className="banner warn">{d.note}</div>
    <div className="stats"><Stat label="Output GST (net of returns)" value={inr(d.output_tax_net)} /><Stat label="Input GST (purchases)" value={inr(d.input_tax)} /><Stat label="Net payable (indicative)" value={inr(d.net_payable)} tone="blue" /></div>
    <Table head={["GST rate", "Taxable value", "CGST", "SGST", "Total tax"]}>{d.output_by_rate.map((r: Row) => <tr key={r.rate}><td>{r.rate}%</td><td className="r">{inr(r.taxable)}</td><td className="r">{inr(r.cgst)}</td><td className="r">{inr(r.sgst)}</td><td className="r">{inr(r.tax)}</td></tr>)}</Table></>);
}
