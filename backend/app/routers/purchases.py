from datetime import date as date_t

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..core import ApiError, get_db, require
from decimal import Decimal

from ..models import (Payment, PaymentAllocation, Product, PurchaseInvoice, PurchaseLine, PurchaseReturn, PurchaseReturnLine, Supplier)
from ..schemas import CancelIn, PurchaseIn, PurchaseReturnIn
from ..services import (audit, ensure_open, get_business, is_interstate, method_account, move_stock, next_number, post_journal, reverse_journals,
                        rnd, today, unwrap_integrity)

router = APIRouter(prefix="/api", tags=["purchases"])


def purchase_out(i: PurchaseInvoice, detail=False) -> dict:
    d = {"id": i.id, "number": i.number, "supplier_invoice_no": i.supplier_invoice_no, "date": i.date.isoformat(),
         "supplier_id": i.supplier_id, "supplier": i.supplier.name, "taxable": i.taxable, "tax_total": i.tax_total,
         "total": i.total, "paid": i.paid, "credited": i.credited, "due": (i.total - i.paid - i.credited) if i.status == "posted" else 0,
         "note": i.note, "status": i.status, "is_igst": i.is_igst, "cancel_reason": i.cancel_reason}
    if detail:
        d["lines"] = [{"product_id": l.product_id, "name": l.name, "qty": float(l.qty), "unit_cost": l.unit_cost,
                       "id": l.id, "gst_rate": float(l.gst_rate), "taxable": l.taxable, "tax": l.tax, "line_total": l.line_total,
                       "returned_qty": float(l.returned_qty)}
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
    ensure_open(db, d)
    biz = get_business(db)
    inv = PurchaseInvoice(number=next_number(db, "pur", "PUR", d), supplier_id=sup.id, supplier_invoice_no=body.supplier_invoice_no.strip(),
                          date=d, user_id=user.id, note=body.note, taxable=0, tax_total=0, total=0, paid=0,
                          credited=0, status="posted", is_igst=is_interstate(biz.state_code, sup.state_code))
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
                                      taxable=taxable, tax=tax, line_total=taxable + tax, returned_qty=0))
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


@router.post("/purchases/{pid}/cancel")
def cancel_purchase(pid: int, body: CancelIn, user=Depends(require("purchases.cancel")), db: Session = Depends(get_db)):
    inv = db.execute(select(PurchaseInvoice).where(PurchaseInvoice.id == pid).with_for_update()).scalar_one_or_none()
    if not inv:
        raise ApiError("Purchase not found", 404)
    if inv.status != "posted":
        raise ApiError("Purchase already cancelled", 409)
    if db.scalar(select(func.count()).select_from(PurchaseReturn).where(PurchaseReturn.invoice_id == pid)):
        raise ApiError("Purchase has returns; cancellation not allowed", 409)
    d = today()
    ensure_open(db, d)
    for l in inv.lines:  # fails with a clear message if the goods were already sold
        move_stock(db, l.product_id, -l.qty, "purchase_cancel", inv.id, user.id, l.unit_cost, f"Cancel {inv.number}")
    reverse_journals(db, "purchase_invoice", inv.id, d, f"Cancel {inv.number}", user.id)
    allocs = db.execute(select(PaymentAllocation, Payment).join(Payment, Payment.id == PaymentAllocation.payment_id)
                        .where(PaymentAllocation.invoice_type == "purchase", PaymentAllocation.invoice_id == pid)).all()
    for a, p in allocs:
        db.add(Payment(date=d, direction="in", method=p.method, amount=a.amount, party_type="supplier", party_id=p.party_id,
                       ref_type="purchase_cancel", ref_id=inv.id, note=f"Refund on cancel {inv.number}", user_id=user.id))
        if p.ref_type != "purchase_invoice":  # purchase-time payment is already undone by the reversed journal
            post_journal(db, d, "purchase_cancel", inv.id, f"Refund {inv.number}",
                         [(method_account(p.method), a.amount, 0), ("AP", 0, a.amount)], user.id)
    inv.status, inv.cancel_reason = "cancelled", body.reason
    audit(db, user, "purchase.cancel", "purchase_invoice", inv.id, body.reason, before={"total": inv.total})
    db.commit()
    return purchase_out(inv, True)


@router.post("/purchases/{pid}/returns")
def purchase_return(pid: int, body: PurchaseReturnIn, user=Depends(require("purchases.return")), db: Session = Depends(get_db)):
    inv = db.execute(select(PurchaseInvoice).where(PurchaseInvoice.id == pid).with_for_update()).scalar_one_or_none()
    if not inv:
        raise ApiError("Purchase not found", 404)
    if inv.status != "posted":
        raise ApiError("Cannot return against a cancelled purchase", 409)
    ensure_open(db, today())
    lines = {l.id: l for l in inv.lines}
    ret = PurchaseReturn(number=next_number(db, "pret", "PR", today()), invoice_id=pid, date=today(), user_id=user.id, reason=body.reason,
                         refund_method=body.refund_method, taxable=0, tax=0, total=0, payable_reduction=0, refund_amount=0)
    cost = 0
    for rl in body.lines:
        l = lines.get(rl.purchase_line_id)
        if not l:
            raise ApiError("Line does not belong to this purchase")
        if rl.qty + l.returned_qty > l.qty:
            raise ApiError(f"Cannot return more than purchased for {l.name} (bought {l.qty}, already returned {l.returned_qty})", 409)
        full = rl.qty + l.returned_qty == l.qty
        prev = db.execute(select(PurchaseReturnLine).where(PurchaseReturnLine.purchase_line_id == l.id)).scalars().all()
        frac = Decimal(rl.qty) / Decimal(l.qty)
        taxable = l.taxable - sum(r.taxable for r in prev) if full else rnd(l.taxable * frac)
        tax = l.tax - sum(r.tax for r in prev) if full else rnd(l.tax * frac)
        ret.lines.append(PurchaseReturnLine(purchase_line_id=l.id, product_id=l.product_id, qty=rl.qty, taxable=taxable, tax=tax, amount=taxable + tax))
        ret.taxable += taxable
        ret.tax += tax
        l.returned_qty += rl.qty
        move_stock(db, l.product_id, -rl.qty, "purchase_return", pid, user.id, l.unit_cost, ret.number)
    ret.total = ret.taxable + ret.tax
    due = max(inv.total - inv.paid - inv.credited, 0)
    ret.payable_reduction = min(ret.total, due)
    ret.refund_amount = ret.total - ret.payable_reduction
    inv.credited += ret.payable_reduction
    db.add(ret)
    db.flush()
    acct = method_account(body.refund_method)
    post_journal(db, today(), "purchase_return", ret.id, f"Return {ret.number}",
                 [("AP", ret.payable_reduction, 0), (acct, ret.refund_amount, 0), ("INV", 0, ret.taxable), ("GST_IN", 0, ret.tax)], user.id)
    if ret.refund_amount:
        db.add(Payment(date=today(), direction="in", method=body.refund_method, amount=ret.refund_amount, party_type="supplier",
                       party_id=inv.supplier_id, ref_type="purchase_return", ref_id=ret.id, note=ret.number, user_id=user.id))
    audit(db, user, "purchase.return", "purchase_return", ret.id, body.reason, after={"purchase": inv.number, "total": ret.total})
    db.commit()
    return {"id": ret.id, "number": ret.number, "total": ret.total, "payable_reduction": ret.payable_reduction, "refund_amount": ret.refund_amount}
