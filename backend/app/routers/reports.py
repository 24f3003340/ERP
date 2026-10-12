import csv
import io
from datetime import date as date_t, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import get_db, require
from ..models import (Customer, Payment, Product, PurchaseInvoice, SalesInvoice, SalesLine, SalesReturn, SalesReturnLine, Supplier)
from ..services import audit, today
from .parties import customer_balance, supplier_balance

router = APIRouter(prefix="/api", tags=["reports"])


def _range(d1, d2):
    return d1 or today().replace(day=1), d2 or today()


@router.get("/dashboard")
def dashboard(user=Depends(require("sales.view")), db: Session = Depends(get_db)):
    t = today()
    posted = SalesInvoice.status == "posted"
    sales_today, bills = db.execute(select(func.coalesce(func.sum(SalesInvoice.total), 0), func.count()).where(SalesInvoice.date == t, posted)).one()
    cash = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.date == t, Payment.method == "cash", Payment.direction == "in"))
    digital = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.date == t, Payment.method != "cash", Payment.direction == "in"))
    recv = db.scalar(select(func.coalesce(func.sum(SalesInvoice.total - SalesInvoice.paid - SalesInvoice.credited), 0)).where(posted))
    pay = db.scalar(select(func.coalesce(func.sum(PurchaseInvoice.total - PurchaseInvoice.paid), 0)))
    low = db.execute(select(Product).where(Product.active.is_(True), Product.stock_qty <= Product.reorder_level, Product.reorder_level > 0).order_by(Product.stock_qty).limit(8)).scalars()
    trend = []
    for k in range(6, -1, -1):
        d = t - timedelta(days=k)
        trend.append({"date": d.isoformat(), "total": db.scalar(select(func.coalesce(func.sum(SalesInvoice.total), 0)).where(SalesInvoice.date == d, posted))})
    top = db.execute(select(SalesLine.name, func.sum(SalesLine.qty), func.sum(SalesLine.line_total)).join(SalesInvoice, SalesInvoice.id == SalesLine.invoice_id)
                     .where(SalesInvoice.date >= t - timedelta(days=30), posted).group_by(SalesLine.name).order_by(func.sum(SalesLine.line_total).desc()).limit(5)).all()
    recent = db.execute(select(SalesInvoice).order_by(SalesInvoice.id.desc()).limit(6)).scalars()
    return {"sales_today": sales_today, "bills_today": bills, "cash_today": cash, "digital_today": digital, "receivables": recv, "payables": pay,
            "low_stock": [{"id": p.id, "name": p.name, "stock": float(p.stock_qty), "reorder": float(p.reorder_level)} for p in low],
            "trend": trend, "top_products": [{"name": n, "qty": float(q), "amount": a} for n, q, a in top],
            "recent": [{"id": i.id, "number": i.number, "total": i.total, "status": i.status, "due": i.total - i.paid - i.credited} for i in recent]}


@router.get("/reports/sales")
def sales_report(date_from: date_t | None = None, date_to: date_t | None = None, group: str = "day", user=Depends(require("reports.view")),
                 db: Session = Depends(get_db)):
    d1, d2 = _range(date_from, date_to)
    base = [SalesInvoice.date >= d1, SalesInvoice.date <= d2, SalesInvoice.status == "posted"]
    rows = db.execute(select(SalesInvoice.date, func.count(), func.sum(SalesInvoice.taxable), func.sum(SalesInvoice.tax_total), func.sum(SalesInvoice.total))
                      .where(*base).group_by(SalesInvoice.date).order_by(SalesInvoice.date)).all()
    ret = db.scalar(select(func.coalesce(func.sum(SalesReturn.total), 0)).where(SalesReturn.date >= d1, SalesReturn.date <= d2))
    pm = db.execute(select(Payment.method, func.sum(Payment.amount)).where(Payment.date >= d1, Payment.date <= d2, Payment.direction == "in",
                    Payment.ref_type.in_(["sales_invoice", "receipt"])).group_by(Payment.method)).all()
    days = [{"date": d.isoformat(), "bills": n, "taxable": t, "tax": x, "total": tot} for d, n, t, x, tot in rows]
    return {"from": d1.isoformat(), "to": d2.isoformat(), "days": days, "total": sum(r["total"] for r in days), "bills": sum(r["bills"] for r in days),
            "returns": ret, "by_method": {m: a for m, a in pm}}


@router.get("/reports/margin")
def margin_report(date_from: date_t | None = None, date_to: date_t | None = None, user=Depends(require("reports.view")), db: Session = Depends(get_db)):
    d1, d2 = _range(date_from, date_to)
    rows = db.execute(select(SalesLine.product_id, SalesLine.name, func.sum(SalesLine.qty - SalesLine.returned_qty), func.sum(SalesLine.taxable),
                             func.sum(SalesLine.cost_price * SalesLine.qty))
                      .join(SalesInvoice, SalesInvoice.id == SalesLine.invoice_id)
                      .where(SalesInvoice.date >= d1, SalesInvoice.date <= d2, SalesInvoice.status == "posted")
                      .group_by(SalesLine.product_id, SalesLine.name).order_by(func.sum(SalesLine.taxable).desc())).all()
    out = [{"product_id": pid, "name": n, "qty": float(q), "revenue": r, "cost": int(c), "margin": r - int(c),
            "margin_pct": round((r - int(c)) * 100 / r, 1) if r else 0} for pid, n, q, r, c in rows]
    return {"rows": out}


@router.get("/reports/stock")
def stock_report(user=Depends(require("reports.view")), db: Session = Depends(get_db)):
    ps = db.execute(select(Product).where(Product.active.is_(True)).order_by(Product.name)).scalars()
    rows = [{"id": p.id, "sku": p.sku, "name": p.name, "stock": float(p.stock_qty), "unit": p.unit, "cost": p.purchase_price,
             "value": round(float(p.stock_qty) * p.purchase_price), "reorder": float(p.reorder_level),
             "low": p.reorder_level > 0 and p.stock_qty <= p.reorder_level} for p in ps]
    return {"rows": rows, "total_value": sum(r["value"] for r in rows)}


@router.get("/reports/dues")
def dues_report(user=Depends(require("reports.view")), db: Session = Depends(get_db)):
    cs = [{"id": c.id, "name": c.name, "phone": c.phone, "balance": customer_balance(db, c.id)} for c in db.execute(select(Customer)).scalars()]
    ss = [{"id": s.id, "name": s.name, "phone": s.phone, "balance": supplier_balance(db, s.id)} for s in db.execute(select(Supplier)).scalars()]
    cs, ss = [c for c in cs if c["balance"]], [s for s in ss if s["balance"]]
    return {"receivables": cs, "payables": ss, "total_receivable": sum(c["balance"] for c in cs), "total_payable": sum(s["balance"] for s in ss)}


@router.get("/reports/gst")
def gst_report(date_from: date_t | None = None, date_to: date_t | None = None, user=Depends(require("reports.view")), db: Session = Depends(get_db)):
    d1, d2 = _range(date_from, date_to)
    out = db.execute(select(SalesLine.gst_rate, func.sum(SalesLine.taxable), func.sum(SalesLine.tax))
                     .join(SalesInvoice, SalesInvoice.id == SalesLine.invoice_id)
                     .where(SalesInvoice.date >= d1, SalesInvoice.date <= d2, SalesInvoice.status == "posted")
                     .group_by(SalesLine.gst_rate).order_by(SalesLine.gst_rate)).all()
    rets = db.execute(select(func.coalesce(func.sum(SalesReturn.taxable), 0), func.coalesce(func.sum(SalesReturn.tax), 0))
                      .where(SalesReturn.date >= d1, SalesReturn.date <= d2)).one()
    inn = db.execute(select(func.coalesce(func.sum(PurchaseInvoice.taxable), 0), func.coalesce(func.sum(PurchaseInvoice.tax_total), 0))
                     .where(PurchaseInvoice.date >= d1, PurchaseInvoice.date <= d2)).one()
    rows = [{"rate": float(r), "taxable": t, "tax": x, "cgst": x // 2, "sgst": x - x // 2} for r, t, x in out]
    out_tax = sum(r["tax"] for r in rows) - rets[1]
    return {"from": d1.isoformat(), "to": d2.isoformat(), "output_by_rate": rows, "sales_return_taxable": rets[0], "sales_return_tax": rets[1],
            "output_tax_net": out_tax, "input_taxable": inn[0], "input_tax": inn[1], "net_payable": out_tax - inn[1],
            "note": "Internal summary only. Verify with your CA before filing returns; this app does not generate e-invoice/IRN."}


@router.get("/reports/export/{kind}")
def export_csv(kind: str, date_from: date_t | None = None, date_to: date_t | None = None, user=Depends(require("export.run")),
               db: Session = Depends(get_db)):
    d1, d2 = _range(date_from, date_to)
    out = io.StringIO()
    w = csv.writer(out)
    if kind == "sales":
        w.writerow(["number", "date", "customer", "status", "taxable", "tax", "round_off", "total", "paid", "due"])
        for i in db.execute(select(SalesInvoice).where(SalesInvoice.date >= d1, SalesInvoice.date <= d2).order_by(SalesInvoice.id)).scalars():
            w.writerow([i.number, i.date, i.customer.name if i.customer else "Walk-in", i.status, i.taxable / 100, i.tax_total / 100,
                        i.round_off / 100, i.total / 100, i.paid / 100, (i.total - i.paid - i.credited) / 100 if i.status == "posted" else 0])
    elif kind == "purchases":
        w.writerow(["number", "date", "supplier", "supplier_invoice", "taxable", "tax", "total", "paid"])
        for i in db.execute(select(PurchaseInvoice).where(PurchaseInvoice.date >= d1, PurchaseInvoice.date <= d2).order_by(PurchaseInvoice.id)).scalars():
            w.writerow([i.number, i.date, i.supplier.name, i.supplier_invoice_no, i.taxable / 100, i.tax_total / 100, i.total / 100, i.paid / 100])
    else:
        from ..core import ApiError
        raise ApiError("Unknown export", 404)
    audit(db, user, f"export.{kind}", kind)
    db.commit()
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={kind}.csv"})
