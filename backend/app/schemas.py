from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Method = Literal["cash", "upi", "card", "bank"]


class SetupIn(BaseModel):
    business_name: str = Field(min_length=1)
    username: str = Field(min_length=3)
    password: str = Field(min_length=8)
    full_name: str = ""
    gstin: str = ""
    address: str = ""
    phone: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str = Field(min_length=3)
    full_name: str = ""
    password: str | None = Field(default=None, min_length=8)
    role: str
    active: bool = True


class BusinessIn(BaseModel):
    name: str
    gstin: str = ""
    address: str = ""
    phone: str = ""
    state_code: str = ""
    invoice_prefix: str = "INV"
    footer: str = ""
    allow_negative_stock: bool = False
    round_total: bool = True
    max_cashier_discount_pct: int = Field(10, ge=0, le=100)
    locale: Literal["en", "hi"] = "en"


class ProductIn(BaseModel):
    sku: str = Field(min_length=1)
    barcode: str | None = None
    name: str = Field(min_length=1)
    category: str = ""
    unit: str = "pcs"
    hsn: str = ""
    sale_price: int = Field(ge=0)
    purchase_price: int = Field(0, ge=0)
    gst_rate: Decimal = Field(Decimal(0), ge=0, le=100)
    price_includes_tax: bool = True
    reorder_level: Decimal = Field(Decimal(0), ge=0)
    opening_qty: Decimal = Field(Decimal(0), ge=0)
    active: bool = True


class PartyIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str = ""
    gstin: str = ""
    address: str = ""
    credit_limit: int = Field(0, ge=0)


class SaleLineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    unit_price: int | None = Field(default=None, ge=0)
    discount: int = Field(0, ge=0)


class PaymentIn(BaseModel):
    method: Method
    amount: int = Field(gt=0)


class SaleIn(BaseModel):
    customer_id: int | None = None
    lines: list[SaleLineIn] = Field(min_length=1)
    payments: list[PaymentIn] = []
    idem_key: str | None = Field(default=None, max_length=60)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3)


class ReturnLineIn(BaseModel):
    sales_line_id: int
    qty: Decimal = Field(gt=0)
    disposition: Literal["restock", "damaged"] = "restock"


class ReturnIn(BaseModel):
    lines: list[ReturnLineIn] = Field(min_length=1)
    refund_method: Method = "cash"
    reason: str = Field(min_length=3)


class PurchaseLineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    unit_cost: int = Field(ge=0)
    gst_rate: Decimal | None = None


class PurchaseIn(BaseModel):
    supplier_id: int
    supplier_invoice_no: str = Field(min_length=1)
    date: dt.date | None = None
    lines: list[PurchaseLineIn] = Field(min_length=1)
    payments: list[PaymentIn] = []
    note: str = ""


class SettleIn(BaseModel):
    amount: int = Field(gt=0)
    method: Method = "cash"
    note: str = ""


class ExpenseIn(BaseModel):
    category: str = Field(min_length=1)
    amount: int = Field(gt=0)
    method: Method = "cash"
    note: str = ""
    date: dt.date | None = None


class AdjustIn(BaseModel):
    product_id: int
    qty_delta: Decimal
    reason: str = Field(min_length=3)


class CountItem(BaseModel):
    product_id: int
    counted: Decimal = Field(ge=0)


class CountIn(BaseModel):
    items: list[CountItem] = Field(min_length=1)
    reason: str = "Physical stock count"
    apply: bool = False


class DayCloseIn(BaseModel):
    date: dt.date | None = None
    counted_cash: int = Field(ge=0)
    reason: str = ""
