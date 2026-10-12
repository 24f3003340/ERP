import csv
import io
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core import ApiError, get_db, require
from ..models import Product, StockMovement
from ..schemas import AdjustIn, CountIn, ProductIn
from ..services import audit, move_stock, post_journal, today, unwrap_integrity, get_business

router = APIRouter(prefix="/api", tags=["products"])


def product_out(p: Product) -> dict:
    d = {c.name: getattr(p, c.name) for c in Product.__table__.columns}
    for k in ("gst_rate", "reorder_level", "stock_qty"):
        d[k] = float(d[k])
    return d


@router.get("/products")
def list_products(q: str = "", category: str = "", low_stock: bool = False, include_inactive: bool = False,
                  limit: int = Query(200, le=1000), offset: int = 0, user=Depends(require("products.view")),
                  db: Session = Depends(get_db)):
    st = select(Product).order_by(Product.name)
    if not include_inactive:
        st = st.where(Product.active.is_(True))
    if q:
        like = f"%{q}%"
        st = st.where(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode == q))
    if category:
        st = st.where(Product.category == category)
    if low_stock:
        st = st.where(Product.stock_qty <= Product.reorder_level)
    return [product_out(p) for p in db.execute(st.limit(limit).offset(offset)).scalars()]


@router.get("/products/lookup")
def lookup(code: str, user=Depends(require("sales.create")), db: Session = Depends(get_db)):
    p = db.execute(select(Product).where(Product.active.is_(True), or_(Product.barcode == code, Product.sku == code))).scalar_one_or_none()
    if not p:
        raise ApiError("Product not found", 404)
    return product_out(p)


@router.get("/categories")
def categories(user=Depends(require("products.view")), db: Session = Depends(get_db)):
    return [c for (c,) in db.execute(select(Product.category).where(Product.category != "").distinct().order_by(Product.category))]


def _create(db: Session, user, body: ProductIn) -> Product:
    p = Product(**body.model_dump(exclude={"opening_qty"}))
    p.barcode = p.barcode or None
    p.sku = p.sku.strip()
    db.add(p)
    db.flush()
    if body.opening_qty > 0:
        move_stock(db, p.id, body.opening_qty, "opening", p.id, user.id, p.purchase_price, "Opening stock")
        val = round(float(body.opening_qty) * p.purchase_price)
        post_journal(db, today(), "opening", p.id, f"Opening stock {p.sku}", [("INV", val, 0), ("OPEN_EQ", 0, val)], user.id)
    audit(db, user, "product.create", "product", p.id, after={"sku": p.sku, "name": p.name})
    return p


@router.post("/products")
def create_product(body: ProductIn, user=Depends(require("products.edit")), db: Session = Depends(get_db)):
    try:
        p = _create(db, user, body)
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise unwrap_integrity(e)
    return product_out(p)


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, user=Depends(require("products.edit")), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise ApiError("Product not found", 404)
    before = {k: str(getattr(p, k)) for k in ("sku", "name", "sale_price", "purchase_price", "gst_rate", "active")}
    for k, v in body.model_dump(exclude={"opening_qty"}).items():
        setattr(p, k, v)
    p.barcode = p.barcode or None
    audit(db, user, "product.update", "product", p.id, before=before,
          after={k: str(getattr(p, k)) for k in before})
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise unwrap_integrity(e)
    return product_out(p)


@router.get("/products/{pid}/ledger")
def stock_ledger(pid: int, user=Depends(require("products.view")), db: Session = Depends(get_db)):
    rows = db.execute(select(StockMovement).where(StockMovement.product_id == pid).order_by(StockMovement.id.desc()).limit(300)).scalars()
    return [{"id": m.id, "at": m.created_at.isoformat(), "qty_delta": float(m.qty_delta), "source_type": m.source_type,
             "source_id": m.source_id, "note": m.note} for m in rows]


def _adjust(db, user, p: Product, delta: Decimal, reason: str, source: str) -> None:
    move_stock(db, p.id, delta, source, p.id, user.id, p.purchase_price, reason, allow_negative=False)
    val = round(float(abs(delta)) * p.purchase_price)
    if delta < 0:
        lines = [("STOCK_ADJ", val, 0), ("INV", 0, val)]
    else:
        lines = [("INV", val, 0), ("STOCK_ADJ", 0, val)]
    post_journal(db, today(), "stock_adj", p.id, f"{source}: {p.name} ({reason})", lines, user.id)
    audit(db, user, "stock.adjust", "product", p.id, reason, after={"qty_delta": str(delta)})


@router.post("/stock/adjust")
def adjust(body: AdjustIn, user=Depends(require("stock.adjust")), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p:
        raise ApiError("Product not found", 404)
    if body.qty_delta == 0:
        raise ApiError("Adjustment quantity is zero")
    _adjust(db, user, p, body.qty_delta, body.reason, "adjustment")
    db.commit()
    return product_out(p)


@router.post("/stock/count")
def stock_count(body: CountIn, user=Depends(require("stock.adjust")), db: Session = Depends(get_db)):
    out = []
    for it in body.items:
        p = db.get(Product, it.product_id)
        if not p:
            raise ApiError(f"Product {it.product_id} not found", 404)
        var = it.counted - p.stock_qty
        out.append({"product_id": p.id, "name": p.name, "system": float(p.stock_qty), "counted": float(it.counted),
                    "variance": float(var), "value_variance": round(float(var) * p.purchase_price)})
        if body.apply and var != 0:
            _adjust(db, user, p, var, body.reason, "count")
    if body.apply:
        db.commit()
    return out


# ---------- CSV import / export ----------
COLS = ["sku", "barcode", "name", "category", "unit", "hsn", "sale_price", "purchase_price", "gst_rate",
        "price_includes_tax", "reorder_level", "opening_qty"]


def _rupees_to_paise(v: str) -> int:
    return int((Decimal(v or "0") * 100).quantize(Decimal(1)))


def _parse(text: str):
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"sku", "name", "sale_price"} <= set(reader.fieldnames):
        raise ApiError("CSV must have columns: sku, name, sale_price (prices in rupees)")
    rows, errors, seen = [], [], set()
    for i, r in enumerate(reader, start=2):
        try:
            sku = (r.get("sku") or "").strip()
            if not sku or not (r.get("name") or "").strip():
                raise ValueError("sku and name required")
            if sku in seen:
                raise ValueError(f"duplicate sku {sku} in file")
            seen.add(sku)
            rows.append(ProductIn(
                sku=sku, barcode=(r.get("barcode") or "").strip() or None, name=r["name"].strip(),
                category=(r.get("category") or "").strip(), unit=(r.get("unit") or "pcs").strip() or "pcs",
                hsn=(r.get("hsn") or "").strip(), sale_price=_rupees_to_paise(r.get("sale_price", "")),
                purchase_price=_rupees_to_paise(r.get("purchase_price", "")),
                gst_rate=Decimal(r.get("gst_rate") or "0"),
                price_includes_tax=(r.get("price_includes_tax") or "true").strip().lower() not in ("0", "false", "no"),
                reorder_level=Decimal(r.get("reorder_level") or "0"), opening_qty=Decimal(r.get("opening_qty") or "0")))
        except (ValueError, InvalidOperation, ArithmeticError) as e:
            errors.append({"row": i, "error": str(e)})
        except Exception as e:  # pydantic validation
            errors.append({"row": i, "error": str(e).splitlines()[0] if str(e) else "invalid row"})
    return rows, errors


@router.post("/products/import")
async def import_products(commit: bool = False, file: UploadFile = File(...), user=Depends(require("import.run")),
                          db: Session = Depends(get_db)):
    """Preview (commit=false) or import (commit=true). Import is all-or-nothing."""
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    rows, errors = _parse(text)
    existing = {s for (s,) in db.execute(select(Product.sku))}
    for r in rows:
        if r.sku in existing:
            errors.append({"row": None, "error": f"sku {r.sku} already exists"})
    result = {"rows": len(rows), "errors": errors, "imported": 0}
    if commit:
        if errors:
            raise ApiError("Fix errors before importing: " + "; ".join(f"{e['row']}: {e['error']}" for e in errors[:5]))
        try:
            for r in rows:
                _create(db, user, r)
            audit(db, user, "import.products", "product", None, f"{len(rows)} rows")
            db.commit()
        except IntegrityError as e:
            db.rollback()
            raise unwrap_integrity(e)
        result["imported"] = len(rows)
    return result


@router.get("/products/export/csv")
def export_products(user=Depends(require("export.run")), db: Session = Depends(get_db)):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLS[:-1] + ["stock_qty"])
    for p in db.execute(select(Product).order_by(Product.sku)).scalars():
        w.writerow([p.sku, p.barcode or "", p.name, p.category, p.unit, p.hsn, p.sale_price / 100, p.purchase_price / 100,
                    p.gst_rate, p.price_includes_tax, p.reorder_level, p.stock_qty])
    audit(db, user, "export.products", "product")
    db.commit()
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=products.csv"})
