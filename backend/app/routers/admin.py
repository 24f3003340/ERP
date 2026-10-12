import base64
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..core import APP_VERSION, BACKUP_DIR, DATABASE_URL, IS_SQLITE, ApiError, engine, get_db, require
from ..models import (JournalEntry, JournalLine, Product, PurchaseInvoice, SalesInvoice, SalesLine, StockMovement)
from ..services import audit

router = APIRouter(prefix="/api", tags=["admin"])


MAGIC = b"ERPENC1"


def _passphrase() -> str | None:
    return os.environ.get("ERP_BACKUP_PASSPHRASE") or None


def _fernet(salt: bytes, passphrase: str) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode())))


def encrypt_in_place(path: Path, passphrase: str) -> Path:
    """Replace backup file with an AES-encrypted copy (name + .enc). Format: MAGIC | salt | Fernet token."""
    salt = os.urandom(16)
    out = path.with_name(path.name + ".enc")
    out.write_bytes(MAGIC + salt + _fernet(salt, passphrase).encrypt(path.read_bytes()))
    path.unlink()
    return out


def plain_copy(path: Path) -> tuple[Path, bool]:
    """Return a readable copy of a backup (decrypting if needed). Caller deletes it when the 2nd value is True."""
    if path.suffix != ".enc":
        return path, False
    pw = _passphrase()
    if not pw:
        raise ApiError("This backup is encrypted. Set ERP_BACKUP_PASSPHRASE to the passphrase used when it was created.", 400)
    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        raise ApiError("Not a valid encrypted backup", 400)
    try:
        data = _fernet(raw[len(MAGIC):len(MAGIC) + 16], pw).decrypt(raw[len(MAGIC) + 16:])
    except InvalidToken:
        raise ApiError("Wrong passphrase or corrupted backup", 400)
    fd, tmp = tempfile.mkstemp(suffix=".restore", dir=BACKUP_DIR)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return Path(tmp), True


def _pg_args():
    u = urlparse(DATABASE_URL.replace("+psycopg2", ""))
    env = {"PGPASSWORD": u.password or "", "PATH": "/usr/bin:/usr/local/bin:/bin:/usr/lib/postgresql/16/bin"}
    return ["-h", u.hostname or "localhost", "-p", str(u.port or 5432), "-U", u.username or ""], u.path.lstrip("/"), env


def sqlite_path() -> Path:
    return Path(DATABASE_URL.replace("sqlite:///", "", 1))


def make_backup(kind: str = "manual") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if IS_SQLITE:
        dest = BACKUP_DIR / f"erp-{kind}-{stamp}.db"
        src = sqlite3.connect(sqlite_path())
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)  # transaction-safe online backup API
        src.close()
        dst.close()
    else:
        dest = BACKUP_DIR / f"erp-{kind}-{stamp}.dump"
        args, dbname, env = _pg_args()
        r = subprocess.run(["pg_dump", "-Fc", *args, "-f", str(dest), dbname], env=env, capture_output=True, text=True)
        if r.returncode:
            dest.unlink(missing_ok=True)
            raise ApiError("pg_dump failed: " + r.stderr[:300], 500)
    if _passphrase():
        dest = encrypt_in_place(dest, _passphrase())  # type: ignore[arg-type]
    prune()
    return dest


def prune(keep_auto: int = 14) -> None:
    autos = sorted(BACKUP_DIR.glob("erp-auto-*"))
    for f in autos[:-keep_auto]:
        f.unlink(missing_ok=True)


def list_backups():
    out = []
    for f in sorted(BACKUP_DIR.glob("erp-*"), reverse=True):
        out.append({"name": f.name, "size": f.stat().st_size, "at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")})
    return out


def verify_sqlite_backup(path: Path) -> dict:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0]
        inv = c.execute("select count(*), coalesce(sum(total),0) from sales_invoices where status='posted'").fetchone()
        bad = c.execute("select count(*) from (select entry_id from journal_lines group by entry_id having sum(debit)<>sum(credit))").fetchone()[0]
        prods = c.execute("select count(*) from products").fetchone()[0]
    finally:
        c.close()
    return {"integrity": ok, "invoices": inv[0], "sales_total": inv[1], "products": prods, "unbalanced_entries": bad,
            "ok": ok == "ok" and bad == 0}


@router.get("/backups")
def backups(user=Depends(require("backup.create"))):
    return {"backups": list_backups(), "mode": "sqlite" if IS_SQLITE else "postgresql", "encrypted": bool(_passphrase())}


@router.post("/backups")
def create_backup(user=Depends(require("backup.create")), db: Session = Depends(get_db)):
    f = make_backup("manual")
    audit(db, user, "backup.create", "backup", None, f.name)
    db.commit()
    return {"name": f.name, "size": f.stat().st_size}


@router.get("/backups/{name}/download")
def download(name: str, user=Depends(require("backup.restore"))):
    f = BACKUP_DIR / Path(name).name
    if not f.exists():
        raise ApiError("Backup not found", 404)
    return FileResponse(f, filename=f.name)  # stays encrypted if encryption is enabled


@router.post("/backups/{name}/verify")
def verify(name: str, user=Depends(require("backup.create"))):
    f = BACKUP_DIR / Path(name).name
    if not f.exists():
        raise ApiError("Backup not found", 404)
    src, tmp = plain_copy(f)
    try:
        if not IS_SQLITE:
            r = subprocess.run(["pg_restore", "-l", str(src)], capture_output=True, text=True)
            return {"ok": r.returncode == 0, "integrity": "pg_restore listing ok" if r.returncode == 0 else r.stderr[:200]}
        return verify_sqlite_backup(src)
    finally:
        if tmp:
            src.unlink(missing_ok=True)


@router.post("/backups/{name}/restore")
def restore(name: str, user=Depends(require("backup.restore")), db: Session = Depends(get_db)):
    f = BACKUP_DIR / Path(name).name
    if not f.exists():
        raise ApiError("Backup not found", 404)
    src, tmp = plain_copy(f)
    try:
        if IS_SQLITE:
            v = verify_sqlite_backup(src)
            if not v["ok"]:
                raise ApiError("Backup failed verification; restore refused", 409)
        else:
            args, dbname, env = _pg_args()
            chk = subprocess.run(["pg_restore", "-l", str(src)], capture_output=True, text=True)
            if chk.returncode:
                raise ApiError("Backup failed verification; restore refused", 409)
            v = {"ok": True, "integrity": "pg_restore listing ok"}
        audit(db, user, "backup.restore", "backup", None, f.name)
        db.commit()
        db.close()
        pre = make_backup("pre-restore")  # safety copy of current data first
        engine.dispose()
        if IS_SQLITE:
            target = sqlite_path()
            for ext in ("-wal", "-shm"):
                Path(str(target) + ext).unlink(missing_ok=True)
            shutil.copyfile(src, target)
        else:
            r = subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", *args, "-d", dbname, str(src)],
                               env=env, capture_output=True, text=True)
            if r.returncode and "error" in r.stderr.lower():
                raise ApiError(f"pg_restore failed (safety copy {pre.name} kept): " + r.stderr[:300], 500)
        return {"restored": f.name, "pre_restore_backup": pre.name, "verify": v}
    finally:
        if tmp:
            src.unlink(missing_ok=True)


@router.get("/diagnostics")
def diagnostics(user=Depends(require("backup.create")), db: Session = Depends(get_db)):
    free = shutil.disk_usage(BACKUP_DIR).free
    bks = list_backups()
    checks = []
    # stock cache == sum of movements
    mism = db.execute(select(func.count()).select_from(
        select(Product.id).outerjoin(StockMovement, StockMovement.product_id == Product.id).group_by(Product.id, Product.stock_qty)
        .having(Product.stock_qty != func.coalesce(func.sum(StockMovement.qty_delta), 0)).subquery())).scalar_one()
    checks.append({"name": "Stock quantity equals stock movement history", "ok": mism == 0, "detail": f"{mism} mismatched products"})
    unb = db.execute(select(func.count()).select_from(
        select(JournalLine.entry_id).group_by(JournalLine.entry_id).having(func.sum(JournalLine.debit) != func.sum(JournalLine.credit)).subquery())).scalar_one()
    checks.append({"name": "All journal entries balance (debit = credit)", "ok": unb == 0, "detail": f"{unb} unbalanced"})
    bad_inv = db.execute(select(func.count()).select_from(
        select(SalesInvoice.id).join(SalesLine, SalesLine.invoice_id == SalesInvoice.id).group_by(SalesInvoice.id, SalesInvoice.total, SalesInvoice.round_off)
        .having(SalesInvoice.total != func.sum(SalesLine.line_total) + SalesInvoice.round_off).subquery())).scalar_one()
    checks.append({"name": "Invoice totals equal line totals", "ok": bad_inv == 0, "detail": f"{bad_inv} mismatched invoices"})
    over = db.scalar(select(func.count()).select_from(SalesInvoice).where(SalesInvoice.paid + SalesInvoice.credited > SalesInvoice.total))
    checks.append({"name": "No invoice over-paid", "ok": over == 0, "detail": f"{over} invoices"})
    neg = db.scalar(select(func.count()).select_from(Product).where(Product.stock_qty < 0))
    checks.append({"name": "No negative stock", "ok": neg == 0, "detail": f"{neg} products"})
    return {"version": APP_VERSION, "database": "SQLite" if IS_SQLITE else "PostgreSQL", "db_url": DATABASE_URL.split("@")[-1] if not IS_SQLITE else str(sqlite_path()),
            "disk_free_mb": free // 1_000_000, "low_disk": free < 500_000_000,
            "last_backup": bks[0] if bks else None, "backup_encryption": bool(_passphrase()), "backup_count": len(bks), "checks": checks, "healthy": all(c["ok"] for c in checks)}
