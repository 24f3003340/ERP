import csv
import io
from datetime import date as date_t

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..core import ApiError, get_db, require
from ..models import Account, AuditLog, DayClose, Expense, JournalEntry, JournalLine, Payment
from ..schemas import DayCloseIn, ExpenseIn
from ..services import audit, method_account, post_journal, today

router = APIRouter(prefix="/api", tags=["accounts"])


@router.post("/expenses")
def add_expense(body: ExpenseIn, user=Depends(require("expenses.create")), db: Session = Depends(get_db)):
    d = body.date or today()
    if d > today():
        raise ApiError("Expense date cannot be in the future")
    e = Expense(date=d, category=body.category.strip(), amount=body.amount, method=body.method, note=body.note, user_id=user.id)
    db.add(e)
    db.flush()
    db.add(Payment(date=d, direction="out", method=body.method, amount=body.amount, ref_type="expense", ref_id=e.id,
                   note=body.category, user_id=user.id))
    post_journal(db, d, "expense", e.id, f"Expense: {e.category}", [("EXP", body.amount, 0), (method_account(body.method), 0, body.amount)], user.id)
    audit(db, user, "expense.create", "expense", e.id, after={"amount": e.amount, "category": e.category})
    db.commit()
    return {"id": e.id}


@router.get("/expenses")
def list_expenses(date_from: date_t | None = None, date_to: date_t | None = None, user=Depends(require("accounts.view")),
                  db: Session = Depends(get_db)):
    st = select(Expense).order_by(Expense.date.desc(), Expense.id.desc()).limit(500)
    if date_from:
        st = st.where(Expense.date >= date_from)
    if date_to:
        st = st.where(Expense.date <= date_to)
    return [{"id": e.id, "date": e.date.isoformat(), "category": e.category, "amount": e.amount, "method": e.method, "note": e.note}
            for e in db.execute(st).scalars()]


def cash_balance(db: Session, upto: date_t) -> int:
    inn = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.method == "cash", Payment.direction == "in", Payment.date <= upto))
    out = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.method == "cash", Payment.direction == "out", Payment.date <= upto))
    return int(inn) - int(out)


@router.get("/cashbook")
def cashbook(date_from: date_t | None = None, date_to: date_t | None = None, method: str = "cash",
             user=Depends(require("accounts.view")), db: Session = Depends(get_db)):
    d1 = date_from or today()
    d2 = date_to or today()
    opening_q = lambda dr: db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.method == method, Payment.direction == dr, Payment.date < d1))
    opening = opening_q("in") - opening_q("out")
    rows = db.execute(select(Payment).where(Payment.method == method, Payment.date >= d1, Payment.date <= d2)
                      .order_by(Payment.id)).scalars()
    bal, out = opening, []
    for p in rows:
        bal += p.amount if p.direction == "in" else -p.amount
        out.append({"id": p.id, "date": p.date.isoformat(), "ref_type": p.ref_type, "ref_id": p.ref_id, "note": p.note,
                    "in": p.amount if p.direction == "in" else 0, "out": p.amount if p.direction == "out" else 0, "balance": bal})
    return {"opening": opening, "closing": bal, "rows": out}


@router.get("/day-close/preview")
def day_close_preview(date: date_t | None = None, user=Depends(require("day.close")), db: Session = Depends(get_db)):
    d = date or today()
    rows = db.execute(select(Payment.method, Payment.direction, func.sum(Payment.amount)).where(Payment.date == d)
                      .group_by(Payment.method, Payment.direction)).all()
    by = {}
    for m, dr, a in rows:
        by.setdefault(m, {"in": 0, "out": 0})[dr] = a
    closed = db.execute(select(DayClose).where(DayClose.date == d)).scalar_one_or_none()
    return {"date": d.isoformat(), "expected_cash": cash_balance(db, d), "opening_cash": cash_balance(db, d) - by.get("cash", {"in": 0, "out": 0})["in"] + by.get("cash", {"in": 0, "out": 0})["out"],
            "by_method": by, "closed": bool(closed),
            "close": {"counted_cash": closed.counted_cash, "variance": closed.variance, "reason": closed.reason} if closed else None}


@router.post("/day-close")
def day_close(body: DayCloseIn, user=Depends(require("day.close")), db: Session = Depends(get_db)):
    d = body.date or today()
    if db.execute(select(DayClose).where(DayClose.date == d)).scalar_one_or_none():
        raise ApiError("This day is already closed", 409)
    expected = cash_balance(db, d)
    var = body.counted_cash - expected
    if var and len(body.reason.strip()) < 3:
        raise ApiError("Cash variance found: please enter a reason", 400)
    dc = DayClose(date=d, expected_cash=expected, counted_cash=body.counted_cash, variance=var, reason=body.reason, closed_by=user.id)
    db.add(dc)
    audit(db, user, "day.close", "day_close", None, body.reason, after={"date": d.isoformat(), "variance": var})
    db.commit()
    return {"expected_cash": expected, "counted_cash": body.counted_cash, "variance": var}


@router.get("/day-closes")
def day_closes(user=Depends(require("day.close")), db: Session = Depends(get_db)):
    return [{"date": c.date.isoformat(), "expected_cash": c.expected_cash, "counted_cash": c.counted_cash, "variance": c.variance,
             "reason": c.reason} for c in db.execute(select(DayClose).order_by(DayClose.date.desc()).limit(60)).scalars()]


def _tb(db: Session, d1: date_t | None, d2: date_t | None):
    st = (select(Account.code, Account.name, Account.type, func.coalesce(func.sum(JournalLine.debit), 0), func.coalesce(func.sum(JournalLine.credit), 0))
          .join(JournalLine, JournalLine.account_id == Account.id, isouter=True)
          .join(JournalEntry, JournalEntry.id == JournalLine.entry_id, isouter=True).group_by(Account.id).order_by(Account.id))
    if d1:
        st = st.where((JournalEntry.date >= d1) | (JournalEntry.id.is_(None)))
    if d2:
        st = st.where((JournalEntry.date <= d2) | (JournalEntry.id.is_(None)))
    return [{"code": c, "name": n, "type": t, "debit": dr, "credit": cr} for c, n, t, dr, cr in db.execute(st).all()]


@router.get("/accounts/trial-balance")
def trial_balance(date_to: date_t | None = None, user=Depends(require("accounts.view")), db: Session = Depends(get_db)):
    rows = _tb(db, None, date_to)
    for r in rows:
        net = r["debit"] - r["credit"]
        r["dr"], r["cr"] = (net, 0) if net >= 0 else (0, -net)
    return {"rows": rows, "total_dr": sum(r["dr"] for r in rows), "total_cr": sum(r["cr"] for r in rows)}


@router.get("/accounts/pnl")
def pnl(date_from: date_t | None = None, date_to: date_t | None = None, user=Depends(require("accounts.view")),
        db: Session = Depends(get_db)):
    rows = _tb(db, date_from, date_to)
    inc = [{"name": r["name"], "amount": r["credit"] - r["debit"]} for r in rows if r["type"] == "income"]
    exp = [{"name": r["name"], "amount": r["debit"] - r["credit"]} for r in rows if r["type"] == "expense"]
    ti, te = sum(i["amount"] for i in inc), sum(e["amount"] for e in exp)
    return {"income": inc, "expenses": exp, "total_income": ti, "total_expenses": te, "net_profit": ti - te}


@router.get("/audit")
def audit_list(action: str = "", limit: int = 200, user=Depends(require("audit.view")), db: Session = Depends(get_db)):
    st = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if action:
        st = st.where(AuditLog.action.ilike(f"{action}%"))
    return [{"id": a.id, "at": a.at.isoformat(), "username": a.username, "action": a.action, "record_type": a.record_type,
             "record_id": a.record_id, "reason": a.reason, "before": a.before, "after": a.after} for a in db.execute(st).scalars()]
