"""Database models. All money is stored as integer paise (INR x 100)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = BigInteger


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    state_code: Mapped[str] = mapped_column(String(4), default="")
    invoice_prefix: Mapped[str] = mapped_column(String(10), default="INV")
    footer: Mapped[str] = mapped_column(Text, default="Thank you! Visit again.")
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    round_total: Mapped[bool] = mapped_column(Boolean, default=True)
    max_cashier_discount_pct: Mapped[int] = mapped_column(Integer, default=10)
    locale: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(60), unique=True)
    barcode: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(80), default="")
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    hsn: Mapped[str] = mapped_column(String(12), default="")
    sale_price: Mapped[int] = mapped_column(Money, default=0)
    purchase_price: Mapped[int] = mapped_column(Money, default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    price_includes_tax: Mapped[bool] = mapped_column(Boolean, default=True)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[int] = mapped_column(Money, default=0)
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    gstin: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    credit_limit: Mapped[int] = mapped_column(Money, default=0)
    state_code: Mapped[str] = mapped_column(String(4), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    state_code: Mapped[str] = mapped_column(String(4), default="")
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    gstin: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"
    __table_args__ = (Index("ix_sales_date", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    idem_key: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default="posted")  # posted | cancelled
    taxable: Mapped[int] = mapped_column(Money, default=0)
    discount_total: Mapped[int] = mapped_column(Money, default=0)
    tax_total: Mapped[int] = mapped_column(Money, default=0)
    round_off: Mapped[int] = mapped_column(Money, default=0)
    total: Mapped[int] = mapped_column(Money, default=0)
    paid: Mapped[int] = mapped_column(Money, default=0)
    credited: Mapped[int] = mapped_column(Money, default=0)  # reduced by returns
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    print_count: Mapped[int] = mapped_column(Integer, default=0)
    is_igst: Mapped[bool] = mapped_column(Boolean, default=False)  # inter-state supply
    lines: Mapped[list["SalesLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    customer: Mapped[Customer | None] = relationship()
    user: Mapped[User] = relationship()


class SalesLine(Base):
    __tablename__ = "sales_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(200))
    hsn: Mapped[str] = mapped_column(String(12), default="")
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_price: Mapped[int] = mapped_column(Money)
    discount: Mapped[int] = mapped_column(Money, default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    price_includes_tax: Mapped[bool] = mapped_column(Boolean, default=True)
    taxable: Mapped[int] = mapped_column(Money)
    tax: Mapped[int] = mapped_column(Money)
    line_total: Mapped[int] = mapped_column(Money)
    cost_price: Mapped[int] = mapped_column(Money, default=0)
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


class PurchaseInvoice(Base):
    __tablename__ = "purchase_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    supplier_invoice_no: Mapped[str] = mapped_column(String(60), default="")
    date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    taxable: Mapped[int] = mapped_column(Money, default=0)
    tax_total: Mapped[int] = mapped_column(Money, default=0)
    total: Mapped[int] = mapped_column(Money, default=0)
    paid: Mapped[int] = mapped_column(Money, default=0)
    note: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(12), default="posted")  # posted | cancelled
    credited: Mapped[int] = mapped_column(Money, default=0)  # reduced by supplier returns
    is_igst: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lines: Mapped[list["PurchaseLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    supplier: Mapped[Supplier] = relationship()
    __table_args__ = (UniqueConstraint("supplier_id", "supplier_invoice_no", name="uq_supplier_invoice"),)


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[int] = mapped_column(Money)  # tax-exclusive
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    taxable: Mapped[int] = mapped_column(Money)
    tax: Mapped[int] = mapped_column(Money)
    line_total: Mapped[int] = mapped_column(Money)
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="lines")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_date", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    method: Mapped[str] = mapped_column(String(10))  # cash | upi | card | bank
    amount: Mapped[int] = mapped_column(Money)
    party_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ref_type: Mapped[str] = mapped_column(String(20))  # sales_invoice|receipt|purchase_invoice|supplier_payment|expense|sales_return|sales_cancel
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    invoice_type: Mapped[str] = mapped_column(String(10))  # sales | purchase
    invoice_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[int] = mapped_column(Money)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(80))
    amount: Mapped[int] = mapped_column(Money)
    method: Mapped[str] = mapped_column(String(10), default="cash")
    note: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SalesReturn(Base):
    __tablename__ = "sales_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    taxable: Mapped[int] = mapped_column(Money, default=0)
    tax: Mapped[int] = mapped_column(Money, default=0)
    total: Mapped[int] = mapped_column(Money, default=0)
    due_reduction: Mapped[int] = mapped_column(Money, default=0)
    refund_amount: Mapped[int] = mapped_column(Money, default=0)
    refund_method: Mapped[str] = mapped_column(String(10), default="cash")
    reason: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lines: Mapped[list["SalesReturnLine"]] = relationship(cascade="all, delete-orphan")


class SalesReturnLine(Base):
    __tablename__ = "sales_return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("sales_returns.id"), index=True)
    sales_line_id: Mapped[int] = mapped_column(ForeignKey("sales_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    disposition: Mapped[str] = mapped_column(String(12), default="restock")  # restock | damaged
    taxable: Mapped[int] = mapped_column(Money)
    tax: Mapped[int] = mapped_column(Money)
    amount: Mapped[int] = mapped_column(Money)


class PurchaseReturn(Base):
    __tablename__ = "purchase_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    taxable: Mapped[int] = mapped_column(Money, default=0)
    tax: Mapped[int] = mapped_column(Money, default=0)
    total: Mapped[int] = mapped_column(Money, default=0)
    payable_reduction: Mapped[int] = mapped_column(Money, default=0)  # reduces what we owe the supplier
    refund_amount: Mapped[int] = mapped_column(Money, default=0)  # money received back from supplier
    refund_method: Mapped[str] = mapped_column(String(10), default="cash")
    reason: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lines: Mapped[list["PurchaseReturnLine"]] = relationship(cascade="all, delete-orphan")


class PurchaseReturnLine(Base):
    __tablename__ = "purchase_return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("purchase_returns.id"), index=True)
    purchase_line_id: Mapped[int] = mapped_column(ForeignKey("purchase_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    taxable: Mapped[int] = mapped_column(Money)
    tax: Mapped[int] = mapped_column(Money)
    amount: Mapped[int] = mapped_column(Money)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(10))  # asset|liability|income|expense|equity


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ref_type: Mapped[str] = mapped_column(String(20), index=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    narration: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    lines: Mapped[list["JournalLine"]] = relationship(cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    debit: Mapped[int] = mapped_column(Money, default=0)
    credit: Mapped[int] = mapped_column(Money, default=0)
    account: Mapped[Account] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(60), default="")
    action: Mapped[str] = mapped_column(String(40), index=True)
    record_type: Mapped[str] = mapped_column(String(30), default="")
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DayClose(Base):
    __tablename__ = "day_closes"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True)
    expected_cash: Mapped[int] = mapped_column(Money)
    counted_cash: Mapped[int] = mapped_column(Money)
    variance: Mapped[int] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(String(200), default="")
    closed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Counter(Base):
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
