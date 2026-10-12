from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import ApiError, get_db, require
from ..models import (Customer, Payment, PaymentAllocation, PurchaseInvoice, SalesInvoice, Supplier)
from ..schemas import PartyIn, SettleIn
from ..services import audit, ensure_open, method_account, post_journal, today

router = APIRouter(prefix="/api", tags=["parties"])


def sales_due(inv: SalesInvoice) -> int:
    return inv.total - inv.paid - inv.credited if inv.status == "posted" else 0


def customer_balance(db: Session, cid: int) -> int:
    return int(db.execute(select(func.coalesce(func.sum(SalesInvoice.total - SalesInvoice.paid - SalesInvoice.credited), 0))
                          .where(SalesInvoice.customer_id == cid, SalesInvoice.status == "posted")).scalar_one())


def supplier_balance(db: Session, sid: int) -> int:
    return int(db.execute(select(func.coalesce(func.sum(PurchaseInvoice.total - PurchaseInvoice.paid - PurchaseInvoice.credited), 0))
                          .where(PurchaseInvoice.supplier_id == sid, PurchaseInvoice.status == "posted")).scalar_one())


def _out(p, bal):
    d = {c.name: getattr(p, c.name) for c in p.__table__.columns}
    d["balance"] = bal
    return d


@router.get("/customers")
def customers(q: str = "", user=Depends(require("parties.view")), db: Session = Depends(get_db)):
    st = select(Customer).where(Customer.active.is_(True)).order_by(Customer.name)
    if q:
        st = st.where(Customer.name.ilike(f"%{q}%") | Customer.phone.ilike(f"%{q}%"))
    return [_out(c, customer_balance(db, c.id)) for c in db.execute(st.limit(500)).scalars()]


@router.post("/customers")
def create_customer(body: PartyIn, user=Depends(require("parties.edit")), db: Session = Depends(get_db)):
    c = Customer(**body.model_dump())
    db.add(c)
    db.flush()
    audit(db, user, "customer.create", "customer", c.id)
    db.commit()
    return _out(c, 0)


@router.put("/customers/{cid}")
def update_customer(cid: int, body: PartyIn, user=Depends(require("parties.edit")), db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if not c:
        raise ApiError("Customer not found", 404)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit(db, user, "customer.update", "customer", c.id)
    db.commit()
    return _out(c, customer_balance(db, c.id))


@router.get("/suppliers")
def suppliers(q: str = "", user=Depends(require("parties.view")), db: Session = Depends(get_db)):
    st = select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)
    if q:
        st = st.where(Supplier.name.ilike(f"%{q}%"))
    return [_out(s, supplier_balance(db, s.id)) for s in db.execute(st.limit(500)).scalars()]


@router.post("/suppliers")
def create_supplier(body: PartyIn, user=Depends(require("parties.edit")), db: Session = Depends(get_db)):
    s = Supplier(**body.model_dump(exclude={"credit_limit"}))
    db.add(s)
    db.flush()
    audit(db, user, "supplier.create", "supplier", s.id)
    db.commit()
    return _out(s, 0)


@router.put("/suppliers/{sid}")
def update_supplier(sid: int, body: PartyIn, user=Depends(require("parties.edit")), db: Session = Depends(get_db)):
    s = db.get(Supplier, sid)
    if not s:
        raise ApiError("Supplier not found", 404)
    for k, v in body.model_dump(exclude={"credit_limit"}).items():
        setattr(s, k, v)
    audit(db, user, "supplier.update", "supplier", s.id)
    db.commit()
    return _out(s, supplier_balance(db, s.id))


def _statement(db, party_type: str, pid: int):
    """Chronological statement with running balance (positive = party owes us / we owe party)."""
    rows = []
    if party_type == "customer":
        for i in db.execute(select(SalesInvoice).where(SalesInvoice.customer_id == pid, SalesInvoice.status == "posted")).scalars():
            rows.append((i.created_at, f"Invoice {i.number}", i.total, 0))
        pays = db.execute(select(Payment).where(Payment.party_type == "customer", Payment.party_id == pid)).scalars()
    else:
        for i in db.execute(select(PurchaseInvoice).where(PurchaseInvoice.supplier_id == pid, PurchaseInvoice.status == "posted")).scalars():
            rows.append((i.created_at, f"Purchase {i.number} ({i.supplier_invoice_no})", i.total, 0))
        pays = db.execute(select(Payment).where(Payment.party_type == "supplier", Payment.party_id == pid)).scalars()
    for p in pays:
        rows.append((p.created_at, f"{p.ref_type} {p.method.upper()}", 0, p.amount if p.direction == ("in" if party_type == "customer" else "out") else -p.amount))
    if party_type == "supplier":
        from ..models import PurchaseReturn
        for r in db.execute(select(PurchaseReturn).join(PurchaseInvoice, PurchaseInvoice.id == PurchaseReturn.invoice_id)
                            .where(PurchaseInvoice.supplier_id == pid)).scalars():
            rows.append((r.created_at, f"Return {r.number}", 0, r.total))
    if party_type == "customer":
        from ..models import SalesReturn
        for r in db.execute(select(SalesReturn).join(SalesInvoice, SalesInvoice.id == SalesReturn.invoice_id)
                            .where(SalesInvoice.customer_id == pid)).scalars():
            rows.append((r.created_at, f"Return {r.number}", 0, r.total))
    rows.sort(key=lambda r: r[0])
    bal, out = 0, []
    for at, desc, debit, credit in rows:
        bal += debit - credit
        out.append({"at": at.isoformat(), "description": desc, "debit": debit, "credit": credit, "balance": bal})
    return out


@router.get("/customers/{cid}/statement")
def customer_statement(cid: int, user=Depends(require("parties.view")), db: Session = Depends(get_db)):
    return _statement(db, "customer", cid)


@router.get("/suppliers/{sid}/statement")
def supplier_statement(sid: int, user=Depends(require("parties.view")), db: Session = Depends(get_db)):
    return _statement(db, "supplier", sid)


def _settle(db, user, kind: str, pid: int, body: SettleIn):
    ensure_open(db, today())
    inv_model = SalesInvoice if kind == "customer" else PurchaseInvoice
    fk = inv_model.customer_id if kind == "customer" else inv_model.supplier_id
    st = select(inv_model).where(fk == pid).order_by(inv_model.created_at)
    if kind == "customer":
        st = st.where(SalesInvoice.status == "posted")
    if kind == "supplier":
        st = st.where(PurchaseInvoice.status == "posted")
    invs = [i for i in db.execute(st.with_for_update()).scalars()
            if (i.total - i.paid - (getattr(i, "credited", 0))) > 0]
    outstanding = sum(i.total - i.paid - getattr(i, "credited", 0) for i in invs)
    if body.amount > outstanding:
        raise ApiError(f"Amount exceeds outstanding balance ({outstanding / 100:.2f})")
    pay = Payment(date=today(), direction="in" if kind == "customer" else "out", method=body.method, amount=body.amount,
                  party_type=kind, party_id=pid, ref_type="receipt" if kind == "customer" else "supplier_payment",
                  note=body.note, user_id=user.id)
    db.add(pay)
    db.flush()
    left = body.amount
    for i in invs:
        if left <= 0:
            break
        take = min(left, i.total - i.paid - getattr(i, "credited", 0))
        i.paid += take
        left -= take
        db.add(PaymentAllocation(payment_id=pay.id, invoice_type="sales" if kind == "customer" else "purchase",
                                 invoice_id=i.id, amount=take))
    acct = method_account(body.method)
    if kind == "customer":
        post_journal(db, today(), "receipt", pay.id, "Customer receipt", [(acct, body.amount, 0), ("AR", 0, body.amount)], user.id)
    else:
        post_journal(db, today(), "supplier_payment", pay.id, "Supplier payment", [("AP", body.amount, 0), (acct, 0, body.amount)], user.id)
    audit(db, user, f"{kind}.settle", kind, pid, after={"amount": body.amount, "method": body.method})
    db.commit()
    return {"payment_id": pay.id}


@router.post("/customers/{cid}/receipts")
def receipt(cid: int, body: SettleIn, user=Depends(require("payments.create")), db: Session = Depends(get_db)):
    if not db.get(Customer, cid):
        raise ApiError("Customer not found", 404)
    return _settle(db, user, "customer", cid, body)


@router.post("/suppliers/{sid}/payments")
def supplier_payment(sid: int, body: SettleIn, user=Depends(require("payments.create")), db: Session = Depends(get_db)):
    if not db.get(Supplier, sid):
        raise ApiError("Supplier not found", 404)
    return _settle(db, user, "supplier", sid, body)
