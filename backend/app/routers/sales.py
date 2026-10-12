from datetime import date as date_t
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..core import ApiError, get_db, has_perm, require
from ..models import (Customer, Payment, PaymentAllocation, Product, SalesInvoice, SalesLine, SalesReturn,
                      SalesReturnLine, StockMovement)
from ..schemas import CancelIn, ReturnIn, SaleIn
from ..services import (audit, calc_line, get_business, method_account, move_stock, next_number, post_journal, rnd,
                        reverse_journals, today, unwrap_integrity)
from .parties import customer_balance, sales_due

router = APIRouter(prefix="/api", tags=["sales"])


def invoice_out(i: SalesInvoice, detail: bool = False) -> dict:
    d = {"id": i.id, "number": i.number, "date": i.date.isoformat(), "created_at": i.created_at.isoformat(),
         "status": i.status, "customer_id": i.customer_id, "customer": i.customer.name if i.customer else "Walk-in",
         "cashier": i.user.username if i.user else "", "taxable": i.taxable, "discount_total": i.discount_total,
         "tax_total": i.tax_total, "round_off": i.round_off, "total": i.total, "paid": i.paid, "credited": i.credited,
         "due": sales_due(i), "cancel_reason": i.cancel_reason, "print_count": i.print_count}
    if detail:
        d["lines"] = [{"id": l.id, "product_id": l.product_id, "name": l.name, "hsn": l.hsn, "unit": l.unit,
                       "qty": float(l.qty), "unit_price": l.unit_price, "discount": l.discount, "gst_rate": float(l.gst_rate),
                       "taxable": l.taxable, "tax": l.tax, "line_total": l.line_total, "returned_qty": float(l.returned_qty)}
                      for l in i.lines]
    return d


@router.post("/sales")
def create_sale(body: SaleIn, user=Depends(require("sales.create")), db: Session = Depends(get_db)):
    biz = get_business(db)
    if body.idem_key:
        dup = db.execute(select(SalesInvoice).where(SalesInvoice.idem_key == body.idem_key)).scalar_one_or_none()
        if dup:  # retried request: return the original invoice, never double-post
            return invoice_out(dup, True)
    d = today()
    inv = SalesInvoice(number=next_number(db, "sales", biz.invoice_prefix, d), idem_key=body.idem_key, date=d,
                       customer_id=body.customer_id, user_id=user.id, taxable=0, discount_total=0, tax_total=0,
                       round_off=0, total=0, paid=0, credited=0, print_count=0)
    if body.customer_id and not db.get(Customer, body.customer_id):
        raise ApiError("Customer not found", 404)
    can_override = has_perm(user.role, "price.override")
    cogs = 0
    gross_list = 0
    # lock products in id order to avoid deadlocks on PostgreSQL
    pids = sorted({l.product_id for l in body.lines})
    prods = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids)).order_by(Product.id).with_for_update()).scalars()}
    for l in body.lines:
        p = prods.get(l.product_id)
        if not p or not p.active:
            raise ApiError(f"Product {l.product_id} not available", 404)
        price = p.sale_price if l.unit_price is None else l.unit_price
        if price != p.sale_price and not can_override:
            raise ApiError(f"Price change for {p.name} needs manager permission", 403)
        max_disc = rnd(Decimal(l.qty) * price * biz.max_cashier_discount_pct / 100)
        if l.discount > max_disc and not can_override:
            raise ApiError(f"Discount on {p.name} exceeds {biz.max_cashier_discount_pct}% limit — manager approval needed", 403)
        taxable, tax, total = calc_line(l.qty, price, l.discount, p.gst_rate, p.price_includes_tax)
        if price != p.sale_price or l.discount:
            audit(db, user, "price.override", "product", p.id, "sale line",
                  before={"price": p.sale_price}, after={"price": price, "discount": l.discount})
        inv.lines.append(SalesLine(product_id=p.id, name=p.name, hsn=p.hsn, unit=p.unit, qty=l.qty, unit_price=price,
                                   discount=l.discount, gst_rate=p.gst_rate, price_includes_tax=p.price_includes_tax,
                                   taxable=taxable, tax=tax, line_total=total, cost_price=p.purchase_price))
        inv.taxable += taxable
        inv.tax_total += tax
        inv.discount_total += l.discount
        gross_list += total
    inv.total = inv.taxable + inv.tax_total
    if biz.round_total:
        inv.round_off = rnd(Decimal(inv.total) / 100) * 100 - inv.total
        inv.total += inv.round_off
    paid = sum(p.amount for p in body.payments)
    if paid > inv.total:
        raise ApiError("Payment is more than the invoice total")
    due = inv.total - paid
    if due > 0:
        if not body.customer_id:
            raise ApiError("Select a customer for credit sale / part payment")
        cust = db.get(Customer, body.customer_id)
        if cust.credit_limit and customer_balance(db, cust.id) + due > cust.credit_limit:
            raise ApiError(f"Credit limit exceeded for {cust.name}", 409)
    inv.paid = paid
    db.add(inv)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise unwrap_integrity(e)
    jl = []
    for l in inv.lines:
        move_stock(db, l.product_id, -l.qty, "sale", inv.id, user.id, l.cost_price, inv.number, biz.allow_negative_stock)
        cogs += rnd(l.qty * l.cost_price)
    for p in body.payments:
        db.add(Payment(date=d, direction="in", method=p.method, amount=p.amount, party_type="customer" if inv.customer_id else None,
                       party_id=inv.customer_id, ref_type="sales_invoice", ref_id=inv.id, user_id=user.id))
        jl.append((method_account(p.method), p.amount, 0))
    db.flush()
    for pay in db.execute(select(Payment).where(Payment.ref_type == "sales_invoice", Payment.ref_id == inv.id)).scalars():
        db.add(PaymentAllocation(payment_id=pay.id, invoice_type="sales", invoice_id=inv.id, amount=pay.amount))
    if due:
        jl.append(("AR", due, 0))
    jl += [("SALES", 0, inv.taxable), ("GST_OUT", 0, inv.tax_total)]
    jl.append(("ROUNDOFF", max(-inv.round_off, 0), max(inv.round_off, 0)))
    post_journal(db, d, "sales_invoice", inv.id, f"Sale {inv.number}", jl, user.id)
    post_journal(db, d, "sales_invoice", inv.id, f"COGS {inv.number}", [("COGS", cogs, 0), ("INV", 0, cogs)], user.id)
    audit(db, user, "sale.create", "sales_invoice", inv.id, after={"number": inv.number, "total": inv.total})
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        if body.idem_key:
            dup = db.execute(select(SalesInvoice).where(SalesInvoice.idem_key == body.idem_key)).scalar_one_or_none()
            if dup:
                return invoice_out(dup, True)
        raise unwrap_integrity(e)
    return invoice_out(inv, True)


@router.get("/sales")
def list_sales(q: str = "", date_from: date_t | None = None, date_to: date_t | None = None, status: str = "",
               customer_id: int | None = None, limit: int = Query(100, le=500), offset: int = 0,
               user=Depends(require("sales.view")), db: Session = Depends(get_db)):
    st = select(SalesInvoice).options(selectinload(SalesInvoice.customer), selectinload(SalesInvoice.user)).order_by(SalesInvoice.id.desc())
    if q:
        st = st.where(SalesInvoice.number.ilike(f"%{q}%"))
    if date_from:
        st = st.where(SalesInvoice.date >= date_from)
    if date_to:
        st = st.where(SalesInvoice.date <= date_to)
    if status:
        st = st.where(SalesInvoice.status == status)
    if customer_id:
        st = st.where(SalesInvoice.customer_id == customer_id)
    return [invoice_out(i) for i in db.execute(st.limit(limit).offset(offset)).scalars()]


@router.get("/sales/{iid}")
def get_sale(iid: int, user=Depends(require("sales.view")), db: Session = Depends(get_db)):
    i = db.get(SalesInvoice, iid)
    if not i:
        raise ApiError("Invoice not found", 404)
    d = invoice_out(i, True)
    d["returns"] = [{"id": r.id, "number": r.number, "date": r.date.isoformat(), "total": r.total, "reason": r.reason}
                    for r in db.execute(select(SalesReturn).where(SalesReturn.invoice_id == iid)).scalars()]
    return d


@router.post("/sales/{iid}/printed")
def mark_printed(iid: int, user=Depends(require("sales.view")), db: Session = Depends(get_db)):
    i = db.get(SalesInvoice, iid)
    if not i:
        raise ApiError("Invoice not found", 404)
    i.print_count += 1
    if i.print_count > 1:
        audit(db, user, "invoice.reprint", "sales_invoice", i.id)
    db.commit()
    return {"print_count": i.print_count}


@router.post("/sales/{iid}/cancel")
def cancel_sale(iid: int, body: CancelIn, user=Depends(require("sales.cancel")), db: Session = Depends(get_db)):
    inv = db.execute(select(SalesInvoice).where(SalesInvoice.id == iid).with_for_update()).scalar_one_or_none()
    if not inv:
        raise ApiError("Invoice not found", 404)
    if inv.status != "posted":
        raise ApiError("Invoice already cancelled", 409)
    if db.scalar(select(func.count()).select_from(SalesReturn).where(SalesReturn.invoice_id == iid)):
        raise ApiError("Invoice has returns; cancellation not allowed", 409)
    d = today()
    for l in inv.lines:
        move_stock(db, l.product_id, l.qty, "sale_cancel", inv.id, user.id, l.cost_price, f"Cancel {inv.number}")
    reverse_journals(db, "sales_invoice", inv.id, d, f"Cancel {inv.number}", user.id)
    allocs = db.execute(select(PaymentAllocation, Payment).join(Payment, Payment.id == PaymentAllocation.payment_id)
                        .where(PaymentAllocation.invoice_type == "sales", PaymentAllocation.invoice_id == iid)).all()
    for a, p in allocs:
        db.add(Payment(date=d, direction="out", method=p.method, amount=a.amount, party_type=p.party_type, party_id=p.party_id,
                       ref_type="sales_cancel", ref_id=inv.id, note=f"Refund on cancel {inv.number}", user_id=user.id))
        if p.ref_type != "sales_invoice":  # sale-time cash already reversed through the journal
            post_journal(db, d, "sales_cancel", inv.id, f"Refund {inv.number}",
                         [("AR", a.amount, 0), (method_account(p.method), 0, a.amount)], user.id)
    inv.status, inv.cancel_reason, inv.cancelled_at = "cancelled", body.reason, today()
    audit(db, user, "invoice.cancel", "sales_invoice", inv.id, body.reason, before={"total": inv.total})
    db.commit()
    return invoice_out(inv, True)


@router.post("/sales/{iid}/returns")
def create_return(iid: int, body: ReturnIn, user=Depends(require("sales.return")), db: Session = Depends(get_db)):
    biz = get_business(db)
    inv = db.execute(select(SalesInvoice).where(SalesInvoice.id == iid).with_for_update()).scalar_one_or_none()
    if not inv:
        raise ApiError("Invoice not found", 404)
    if inv.status != "posted":
        raise ApiError("Cannot return against a cancelled invoice", 409)
    lines = {l.id: l for l in inv.lines}
    ret = SalesReturn(number=next_number(db, "sret", "SR", today()), invoice_id=iid, date=today(), user_id=user.id,
                      reason=body.reason, refund_method=body.refund_method, taxable=0, tax=0, total=0,
                      due_reduction=0, refund_amount=0)
    restock_cost = 0
    for rl in body.lines:
        l = lines.get(rl.sales_line_id)
        if not l:
            raise ApiError("Line does not belong to this invoice")
        if rl.qty + l.returned_qty > l.qty:
            raise ApiError(f"Cannot return more than sold for {l.name} (sold {l.qty}, already returned {l.returned_qty})", 409)
        frac = Decimal(rl.qty) / Decimal(l.qty)
        full = rl.qty + l.returned_qty == l.qty
        prev = [r for r in db.execute(select(SalesReturnLine).where(SalesReturnLine.sales_line_id == l.id)).scalars()]
        taxable = l.taxable - sum(r.taxable for r in prev) if full else rnd(l.taxable * frac)
        tax = l.tax - sum(r.tax for r in prev) if full else rnd(l.tax * frac)
        ret.lines.append(SalesReturnLine(sales_line_id=l.id, product_id=l.product_id, qty=rl.qty, disposition=rl.disposition,
                                         taxable=taxable, tax=tax, amount=taxable + tax))
        ret.taxable += taxable
        ret.tax += tax
        l.returned_qty += rl.qty
        if rl.disposition == "restock":
            move_stock(db, l.product_id, rl.qty, "sale_return", iid, user.id, l.cost_price, ret.number)
            restock_cost += rnd(rl.qty * l.cost_price)
    ret.total = ret.taxable + ret.tax
    due = sales_due(inv)
    ret.due_reduction = min(ret.total, max(due, 0))
    ret.refund_amount = ret.total - ret.due_reduction
    inv.credited += ret.due_reduction
    db.add(ret)
    db.flush()
    jl = [("SALES_RET", ret.taxable, 0), ("GST_OUT", ret.tax, 0), ("AR", 0, ret.due_reduction),
          (method_account(body.refund_method), 0, ret.refund_amount)]
    post_journal(db, today(), "sales_return", ret.id, f"Return {ret.number}", jl, user.id)
    if restock_cost:
        post_journal(db, today(), "sales_return", ret.id, f"Restock {ret.number}", [("INV", restock_cost, 0), ("COGS", 0, restock_cost)], user.id)
    if ret.refund_amount:
        db.add(Payment(date=today(), direction="out", method=body.refund_method, amount=ret.refund_amount,
                       party_type="customer" if inv.customer_id else None, party_id=inv.customer_id, ref_type="sales_return",
                       ref_id=ret.id, note=ret.number, user_id=user.id))
    audit(db, user, "sale.return", "sales_return", ret.id, body.reason, after={"invoice": inv.number, "total": ret.total})
    db.commit()
    return {"id": ret.id, "number": ret.number, "total": ret.total, "due_reduction": ret.due_reduction,
            "refund_amount": ret.refund_amount}
