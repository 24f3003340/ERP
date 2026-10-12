from datetime import date as date_t

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..core import ApiError, get_db, require
from ..models import Payment, PaymentAllocation, Product, PurchaseInvoice, PurchaseLine, Supplier
from ..schemas import PurchaseIn
from ..services import audit, method_account, move_stock, next_number, post_journal, rnd, today, unwrap_integrity

router = APIRouter(prefix="/api", tags=["purchases"])


def purchase_out(i: PurchaseInvoice, detail=False) -> dict:
    d = {"id": i.id, "number": i.number, "supplier_invoice_no": i.supplier_invoice_no, "date": i.date.isoformat(),
         "supplier_id": i.supplier_id, "supplier": i.supplier.name, "taxable": i.taxable, "tax_total": i.tax_total,
         "total": i.total, "paid": i.paid, "due": i.total - i.paid, "note": i.note}
    if detail:
        d["lines"] = [{"product_id": l.product_id, "name": l.name, "qty": float(l.qty), "unit_cost": l.unit_cost,
                       "gst_rate": float(l.gst_rate), "taxable": l.taxable, "tax": l.tax, "line_total": l.line_total}
                      for l in i.lines]
    return d


@router.post("/purchases")
def create_purchase(body: PurchaseIn, user=Depends(require("purchases.create")), db: Session = Depends(get_db)):
    sup = db.get(Supplier, body.supplier_id)
    if not sup:
        raise ApiError("Supplier not found", 404)
    d = body.date or today()
    if d > today():
        raise ApiError("Purchase date cannot be in the future")
    inv = PurchaseInvoice(number=next_number(db, "pur", "PUR", d), supplier_id=sup.id, supplier_invoice_no=body.supplier_invoice_no.strip(),
                          date=d, user_id=user.id, note=body.note, taxable=0, tax_total=0, total=0, paid=0)
    pids = sorted({l.product_id for l in body.lines})
    prods = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids)).order_by(Product.id).with_for_update()).scalars()}
    for l in body.lines:
        p = prods.get(l.product_id)
        if not p:
            raise ApiError(f"Product {l.product_id} not found", 404)
        rate = p.gst_rate if l.gst_rate is None else l.gst_rate
        taxable = rnd(l.qty * l.unit_cost)
        tax = rnd(taxable * rate / 100)
        inv.lines.append(PurchaseLine(product_id=p.id, name=p.name, qty=l.qty, unit_cost=l.unit_cost, gst_rate=rate,
                                      taxable=taxable, tax=tax, line_total=taxable + tax))
        inv.taxable += taxable
        inv.tax_total += tax
    inv.total = inv.taxable + inv.tax_total
    paid = sum(p.amount for p in body.payments)
    if paid > inv.total:
        raise ApiError("Payment is more than purchase total")
    inv.paid = paid
    db.add(inv)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        if "uq_supplier_invoice" in str(e.orig) or "supplier_invoice_no" in str(e.orig):
            raise ApiError("This supplier invoice number is already entered", 409)
        raise unwrap_integrity(e)
    for l in inv.lines:
        p = prods[l.product_id]
        # moving-average style: keep latest cost as the product's purchase price
        p.purchase_price = l.unit_cost
        move_stock(db, p.id, l.qty, "purchase", inv.id, user.id, l.unit_cost, inv.number)
    jl = [("INV", inv.taxable, 0), ("GST_IN", inv.tax_total, 0)]
    for pm in body.payments:
        pay = Payment(date=d, direction="out", method=pm.method, amount=pm.amount, party_type="supplier", party_id=sup.id,
                      ref_type="purchase_invoice", ref_id=inv.id, user_id=user.id)
        db.add(pay)
        db.flush()
        db.add(PaymentAllocation(payment_id=pay.id, invoice_type="purchase", invoice_id=inv.id, amount=pm.amount))
        jl.append((method_account(pm.method), 0, pm.amount))
    jl.append(("AP", 0, inv.total - paid))
    post_journal(db, d, "purchase_invoice", inv.id, f"Purchase {inv.number}", jl, user.id)
    audit(db, user, "purchase.create", "purchase_invoice", inv.id, after={"number": inv.number, "total": inv.total})
    db.commit()
    return purchase_out(inv, True)


@router.get("/purchases")
def list_purchases(supplier_id: int | None = None, limit: int = Query(100, le=500), user=Depends(require("purchases.view")),
                   db: Session = Depends(get_db)):
    st = select(PurchaseInvoice).options(selectinload(PurchaseInvoice.supplier)).order_by(PurchaseInvoice.id.desc())
    if supplier_id:
        st = st.where(PurchaseInvoice.supplier_id == supplier_id)
    return [purchase_out(i) for i in db.execute(st.limit(limit)).scalars()]


@router.get("/purchases/{pid}")
def get_purchase(pid: int, user=Depends(require("purchases.view")), db: Session = Depends(get_db)):
    i = db.get(PurchaseInvoice, pid)
    if not i:
        raise ApiError("Purchase not found", 404)
    return purchase_out(i, True)
