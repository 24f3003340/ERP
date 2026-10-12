import { Link } from "react-router-dom";
import { fdate, inr } from "../api";
import { api } from "../api";
import { Badge, Empty, Loading, Stat, useAsync, useSession } from "../ui";
import { t } from "../i18n";

export default function Dashboard() {
  const { business, can } = useSession();
  const { data: d, error, loading } = useAsync(() => api("/dashboard"), []);
  if (loading) return <Loading />;
  if (error || !d) return <Empty>{error}</Empty>;
  const max = Math.max(1, ...d.trend.map((x: any) => x.total));
  return (
    <div>
      <div className="page-head">
        <div><h2>{business.name}</h2><span className="muted">{fdate(new Date().toISOString())}</span></div>
        <div className="actions">
          {can("sales.create") && <Link className="btn primary" to="/billing">+ {t("newBill")}</Link>}
          {can("purchases.create") && <Link className="btn" to="/purchases">+ Purchase</Link>}
          {can("products.edit") && <Link className="btn" to="/products">+ Product</Link>}
        </div>
      </div>
      <div className="stats">
        <Stat label={t("salesToday")} value={inr(d.sales_today)} tone="blue" />
        <Stat label={t("bills")} value={d.bills_today} />
        <Stat label="Cash in today" value={inr(d.cash_today)} />
        <Stat label="UPI / Card today" value={inr(d.digital_today)} />
        <Stat label={t("receivables")} value={inr(d.receivables)} tone="amber" />
        <Stat label={t("payables")} value={inr(d.payables)} />
      </div>
      <div className="grid2 gap">
        <section className="card">
          <h3>Sales — last 7 days</h3>
          <div className="bars" role="img" aria-label="Sales trend">
            {d.trend.map((x: any) => (
              <div key={x.date} className="bar-col" title={inr(x.total)}>
                <div className="bar" style={{ height: `${(x.total / max) * 100}%` }} />
                <small>{new Date(x.date).toLocaleDateString("en-IN", { weekday: "short" })}</small>
              </div>
            ))}
          </div>
        </section>
        <section className="card">
          <h3>Top products (30 days)</h3>
          {d.top_products.length === 0 ? <Empty>No sales yet. Make your first bill to see this.</Empty> :
            d.top_products.map((p: any) => (<div key={p.name} className="row-between"><span>{p.name}</span><b>{inr(p.amount)}</b></div>))}
        </section>
        <section className="card">
          <h3>{t("lowStock")}</h3>
          {d.low_stock.length === 0 ? <Empty>No low-stock items 🎉 (set reorder levels on products)</Empty> :
            d.low_stock.map((p: any) => (<div key={p.id} className="row-between"><span>{p.name}</span><Badge tone="warn">{p.stock} left (min {p.reorder})</Badge></div>))}
        </section>
        <section className="card">
          <h3>Recent bills</h3>
          {d.recent.length === 0 ? <Empty>No bills yet.</Empty> :
            d.recent.map((i: any) => (
              <div key={i.id} className="row-between"><span>{i.number}</span>
                <span>{i.status === "cancelled" ? <Badge tone="err">cancelled</Badge> : i.due > 0 ? <Badge tone="warn">due {inr(i.due)}</Badge> : null} <b>{inr(i.total)}</b></span>
              </div>))}
        </section>
      </div>
    </div>
  );
}
