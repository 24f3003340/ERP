import { useState } from "react";
import { api, inr, Row, toPaise } from "../api";
import { Badge, Empty, Field, Loading, Stat, Table, useAsync, useSession, useToast } from "../ui";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

export default function Accounts() {
  const { can } = useSession();
  const [tab, setTab] = useState("cash");
  const tabs: [string, string][] = [["cash", "Cashbook"], ["expenses", "Expenses"], ["day", "Day close"], ["tb", "Trial balance"], ["pnl", "Profit & Loss"]];
  return (
    <div>
      <div className="page-head"><h2>Accounts</h2></div>
      <div className="tabs">{tabs.map(([k, l]) => <button key={k} className={"tab" + (tab === k ? " active" : "")} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === "cash" && <Cashbook />}
      {tab === "expenses" && <Expenses canAdd={can("expenses.create")} />}
      {tab === "day" && <DayClose />}
      {tab === "tb" && <TB />}
      {tab === "pnl" && <PnL />}
    </div>
  );
}

function Cashbook() {
  const [method, setMethod] = useState("cash"); const [from, setFrom] = useState(today()); const [to, setTo] = useState(today());
  const { data, loading } = useAsync(() => api("/cashbook", { params: { method, date_from: from, date_to: to } }), [method, from, to]);
  return (
    <div>
      <div className="filters"><select value={method} onChange={(e) => setMethod(e.target.value)}><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option><option value="bank">Bank</option></select>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
      {loading || !data ? <Loading /> : (<>
        <div className="stats"><Stat label="Opening" value={inr(data.opening)} /><Stat label="Closing" value={inr(data.closing)} tone="blue" /></div>
        {data.rows.length === 0 ? <Empty>No entries in this period.</Empty> : (
          <Table head={["Date", "Type", "Note", "In", "Out", "Balance"]}>
            {data.rows.map((r: Row) => (<tr key={r.id}><td>{r.date}</td><td>{r.ref_type}</td><td>{r.note}</td><td className="r pos">{r.in ? inr(r.in) : ""}</td><td className="r neg">{r.out ? inr(r.out) : ""}</td><td className="r">{inr(r.balance)}</td></tr>))}
          </Table>)}
      </>)}
    </div>
  );
}

function Expenses({ canAdd }: { canAdd: boolean }) {
  const toast = useToast();
  const [f, setF] = useState({ category: "", amount: "", method: "cash", note: "" }); const [err, setErr] = useState("");
  const { data, loading, reload } = useAsync(() => api("/expenses"), []);
  async function add() {
    try { await api("/expenses", { body: { ...f, amount: toPaise(f.amount) } }); toast("Expense recorded"); setF({ category: "", amount: "", method: "cash", note: "" }); setErr(""); reload(); } catch (e: any) { setErr(e.message); }
  }
  return (
    <div>
      {canAdd && (<div className="card"><div className="grid4">
        <Field label="Category"><input list="expcats" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} /><datalist id="expcats">{["Rent", "Electricity", "Salary", "Transport", "Tea/Snacks", "Repairs", "Misc"].map((c) => <option key={c} value={c} />)}</datalist></Field>
        <Field label="Amount ₹"><input type="number" min="0" step="0.01" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Paid via"><select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}><option value="cash">Cash</option><option value="upi">UPI</option><option value="bank">Bank</option></select></Field>
        <Field label="Note"><input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field></div>
        {err && <div className="error">{err}</div>}
        <button className="btn primary" disabled={!f.category.trim() || toPaise(f.amount) <= 0} onClick={add}>Add expense</button></div>)}
      {loading ? <Loading /> : !data?.length ? <Empty>No expenses recorded.</Empty> : (
        <Table head={["Date", "Category", "Method", "Note", "Amount"]}>{data.map((e: Row) => (<tr key={e.id}><td>{e.date}</td><td>{e.category}</td><td>{e.method}</td><td>{e.note}</td><td className="r">{inr(e.amount)}</td></tr>))}</Table>)}
    </div>
  );
}

function DayClose() {
  const toast = useToast();
  const { can } = useSession();
  const { data, loading, reload } = useAsync(() => api("/day-close/preview"), []);
  const hist = useAsync(() => api("/day-closes"), []);
  const [counted, setCounted] = useState(""); const [reason, setReason] = useState(""); const [err, setErr] = useState("");
  async function close() {
    try { const r = await api("/day-close", { body: { counted_cash: toPaise(counted), reason } }); toast(r.variance ? `Day closed with variance ${inr(r.variance)}` : "Day closed — cash matches"); reload(); hist.reload(); setErr(""); } catch (e: any) { setErr(e.message); }
  }
  if (loading || !data) return <Loading />;
  const variance = toPaise(counted) - data.expected_cash;
  return (
    <div>
      <div className="stats"><Stat label="Expected cash in drawer" value={inr(data.expected_cash)} tone="blue" />
        {Object.entries(data.by_method as Row).map(([m, v]: [string, any]) => <Stat key={m} label={`${m.toUpperCase()} today (in / out)`} value={`${inr(v.in)} / ${inr(v.out)}`} />)}</div>
      {data.closed ? <div className="banner ok">Today is closed — new bills, purchases, expenses and payments are blocked. Counted {inr(data.close.counted_cash)}, variance {inr(data.close.variance)} {data.close.reason && `(${data.close.reason})`}
        {can("day.reopen") && <> <button className="btn sm" onClick={async () => { const r = prompt("Reason for reopening today (recorded in audit log):"); if (!r) return; try { await api("/day-close/reopen", { body: { date: data.date, reason: r } }); toast("Day reopened"); reload(); hist.reload(); } catch (e: any) { toast(e.message, "err"); } }}>Reopen day</button></>}</div> : (
        <div className="card"><h3>Close today</h3>
          <div className="grid3"><Field label="Counted cash ₹"><input type="number" min="0" step="0.01" value={counted} onChange={(e) => setCounted(e.target.value)} /></Field>
            <Field label={`Reason ${counted && variance !== 0 ? "(required — variance " + inr(variance) + ")" : ""}`}><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field></div>
          {err && <div className="error">{err}</div>}
          <button className="btn primary" disabled={counted === ""} onClick={close}>Close day</button></div>)}
      <h3>History</h3>
      {hist.data?.length ? <Table head={["Date", "Expected", "Counted", "Variance", "Reason"]}>{hist.data.map((c: Row) => (<tr key={c.date}><td>{c.date}</td><td className="r">{inr(c.expected_cash)}</td><td className="r">{inr(c.counted_cash)}</td><td className="r">{c.variance ? <Badge tone="warn">{inr(c.variance)}</Badge> : "—"}</td><td>{c.reason}</td></tr>))}</Table> : <Empty>No closed days yet.</Empty>}
    </div>
  );
}

function TB() {
  const { data, loading } = useAsync(() => api("/accounts/trial-balance"), []);
  if (loading || !data) return <Loading />;
  return (<div><Table head={["Account", "Type", "Debit", "Credit"]}>{data.rows.map((r: Row) => (<tr key={r.code}><td>{r.name}</td><td>{r.type}</td><td className="r">{r.dr ? inr(r.dr) : ""}</td><td className="r">{r.cr ? inr(r.cr) : ""}</td></tr>))}
    <tr className="total"><td colSpan={2}><b>Total</b></td><td className="r"><b>{inr(data.total_dr)}</b></td><td className="r"><b>{inr(data.total_cr)}</b></td></tr></Table>
    {data.total_dr === data.total_cr ? <Badge tone="ok">Balanced ✓</Badge> : <Badge tone="err">Books do not balance!</Badge>}</div>);
}

function PnL() {
  const [from, setFrom] = useState(monthStart()); const [to, setTo] = useState(today());
  const { data, loading } = useAsync(() => api("/accounts/pnl", { params: { date_from: from, date_to: to } }), [from, to]);
  return (<div><div className="filters"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
    {loading || !data ? <Loading /> : (<div className="grid2 gap">
      <div className="card"><h3>Income</h3>{data.income.map((i: Row) => <div key={i.name} className="row-between"><span>{i.name}</span><span>{inr(i.amount)}</span></div>)}<div className="row-between grand"><span>Total</span><span>{inr(data.total_income)}</span></div></div>
      <div className="card"><h3>Expenses</h3>{data.expenses.map((i: Row) => <div key={i.name} className="row-between"><span>{i.name}</span><span>{inr(i.amount)}</span></div>)}<div className="row-between grand"><span>Total</span><span>{inr(data.total_expenses)}</span></div></div>
      <div className="card"><h3>Net profit</h3><div className={"big-num " + (data.net_profit < 0 ? "neg" : "pos")}>{inr(data.net_profit)}</div></div></div>)}</div>);
}
