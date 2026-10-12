"""Business rules: tax maths, numbering, stock, double-entry posting, audit."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .core import ApiError
from .models import (Account, AuditLog, Business, Counter, JournalEntry, JournalLine, Product, StockMovement)

D = Decimal

ACCOUNTS = [
    ("CASH", "Cash in hand", "asset"), ("BANK", "Bank / UPI / Card", "asset"),
    ("AR", "Accounts receivable (customers)", "asset"), ("INV", "Inventory", "asset"),
    ("GST_IN", "GST input credit", "asset"), ("AP", "Accounts payable (suppliers)", "liability"),
    ("GST_OUT", "GST output payable", "liability"), ("OPEN_EQ", "Opening balance equity", "equity"),
    ("SALES", "Sales", "income"), ("ROUNDOFF", "Round off", "income"),
    ("SALES_RET", "Sales returns", "expense"), ("COGS", "Cost of goods sold", "expense"),
    ("EXP", "Operating expenses", "expense"), ("STOCK_ADJ", "Stock adjustments / shrinkage", "expense"),
]


def seed_accounts(db: Session) -> None:
    have = {c for (c,) in db.execute(select(Account.code))}
    for code, name, typ in ACCOUNTS:
        if code not in have:
            db.add(Account(code=code, name=name, type=typ))
    db.flush()


def today() -> date:
    return date.today()


def fin_year(d: date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def next_number(db: Session, kind: str, prefix: str, d: date) -> str:
    name = f"{kind}-{fin_year(d)}"
    if db.get(Counter, name) is None:
        try:
            with db.begin_nested():
                db.add(Counter(name=name, value=0))
        except IntegrityError:
            pass
    db.execute(update(Counter).where(Counter.name == name).values(value=Counter.value + 1))
    value = db.execute(select(Counter.value).where(Counter.name == name)).scalar_one()
    return f"{prefix}/{fin_year(d)}/{value:06d}"


def rnd(x: Decimal) -> int:
    return int(x.quantize(D(1), rounding=ROUND_HALF_UP))


def calc_line(qty: Decimal, unit_price: int, discount: int, rate: Decimal, inclusive: bool) -> tuple[int, int, int]:
    """Return (taxable, tax, line_total) in paise."""
    gross = rnd(qty * unit_price) - discount
    if gross < 0:
        raise ApiError("Discount cannot exceed line amount")
    if inclusive:
        taxable = rnd(D(gross) * 100 / (100 + rate))
        tax = gross - taxable
    else:
        taxable = gross
        tax = rnd(D(gross) * rate / 100)
    return taxable, tax, taxable + tax


def get_business(db: Session) -> Business:
    b = db.execute(select(Business).limit(1)).scalar_one_or_none()
    if not b:
        raise ApiError("Business not set up yet", 409)
    return b


# ---------- accounting ----------
def post_journal(db: Session, d: date, ref_type: str, ref_id: int | None, narration: str, lines: list[tuple[str, int, int]],
                 user_id: int | None = None) -> JournalEntry:
    lines = [(c, dr, cr) for c, dr, cr in lines if dr or cr]
    if sum(l[1] for l in lines) != sum(l[2] for l in lines):
        raise ApiError("Internal error: unbalanced journal entry", 500)
    if not lines:
        return None  # type: ignore
    accs = {a.code: a.id for a in db.execute(select(Account)).scalars()}
    je = JournalEntry(date=d, ref_type=ref_type, ref_id=ref_id, narration=narration, user_id=user_id)
    for code, dr, cr in lines:
        je.lines.append(JournalLine(account_id=accs[code], debit=dr, credit=cr))
    db.add(je)
    db.flush()
    return je


def reverse_journals(db: Session, ref_type: str, ref_id: int, d: date, narration: str, user_id: int | None) -> None:
    for je in db.execute(select(JournalEntry).where(JournalEntry.ref_type == ref_type, JournalEntry.ref_id == ref_id)).scalars():
        rev = JournalEntry(date=d, ref_type=f"{ref_type}_rev", ref_id=ref_id, narration=narration, user_id=user_id)
        for l in je.lines:
            rev.lines.append(JournalLine(account_id=l.account_id, debit=l.credit, credit=l.debit))
        db.add(rev)
    db.flush()


def method_account(method: str) -> str:
    return "CASH" if method == "cash" else "BANK"


# ---------- stock ----------
def move_stock(db: Session, product_id: int, delta: Decimal, source_type: str, source_id: int | None, user_id: int | None,
               unit_cost: int = 0, note: str = "", allow_negative: bool = False) -> None:
    """Atomically change stock; refuses to go below zero unless allowed."""
    cond = [Product.id == product_id]
    if delta < 0 and not allow_negative:
        cond.append(Product.stock_qty + delta >= 0)
    res = db.execute(update(Product).where(*cond).values(stock_qty=Product.stock_qty + delta))
    if res.rowcount != 1:
        p = db.get(Product, product_id)
        name = p.name if p else f"#{product_id}"
        have = p.stock_qty if p else 0
        raise ApiError(f"Insufficient stock for {name} (available {have})", 409)
    db.add(StockMovement(product_id=product_id, qty_delta=delta, unit_cost=unit_cost, source_type=source_type,
                         source_id=source_id, note=note, user_id=user_id))


# ---------- audit ----------
def _plain(d: dict | None) -> dict | None:
    """JSON-safe copy (PostgreSQL returns Decimal for SUM of integers)."""
    if d is None:
        return None
    return {k: (int(v) if isinstance(v, Decimal) and v == v.to_integral_value() else float(v) if isinstance(v, Decimal) else v)
            for k, v in d.items()}


def audit(db: Session, user, action: str, record_type: str = "", record_id: int | None = None, reason: str = "",
          before: dict | None = None, after: dict | None = None) -> None:
    before, after = _plain(before), _plain(after)
    db.add(AuditLog(user_id=getattr(user, "id", None), username=getattr(user, "username", ""), action=action,
                    record_type=record_type, record_id=record_id, reason=reason, before=before, after=after))


def unwrap_integrity(e: IntegrityError) -> ApiError:
    msg = str(e.orig).lower()
    if "unique" in msg or "duplicate" in msg:
        return ApiError("Duplicate value: a record with the same unique field already exists", 409)
    return ApiError("Database constraint failed: " + str(e.orig).split("\n")[0], 409)
