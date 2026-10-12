"""Config, database engine, security helpers and permission checks."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

DATA_DIR = Path(os.environ.get("ERP_DATA_DIR", Path.home() / ".local-erp")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("ERP_DATABASE_URL", f"sqlite:///{(DATA_DIR / 'erp.db').as_posix()}")
IS_SQLITE = DATABASE_URL.startswith("sqlite")
APP_VERSION = "1.0.0"


def _load_secret() -> str:
    env = os.environ.get("ERP_SECRET_KEY")
    if env:
        return env
    f = DATA_DIR / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        try:
            f.chmod(0o600)
        except OSError:
            pass
    return f.read_text().strip()


SECRET_KEY = _load_secret()
TOKEN_HOURS = 12

_kwargs: dict = {"pool_pre_ping": True}
if IS_SQLITE:
    _kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
engine = create_engine(DATABASE_URL, **_kwargs)

if IS_SQLITE:
    # Explicit BEGIN IMMEDIATE so concurrent writers serialise instead of losing updates.
    @event.listens_for(engine, "connect")
    def _sqlite_connect(dbapi_conn, _):
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------- security ----------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except ValueError:
        return False


def make_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, SECRET_KEY, algorithm="HS256")


ROLES = ["owner", "manager", "cashier", "stock", "accountant"]
_ALL_BUT_ADMIN = {
    "products.view", "products.edit", "stock.adjust", "sales.create", "sales.view", "sales.cancel",
    "sales.return", "price.override", "purchases.create", "purchases.view", "purchases.cancel", "purchases.return", "parties.view",
    "parties.edit", "payments.create", "expenses.create", "reports.view", "accounts.view",
    "day.close", "audit.view", "import.run", "export.run", "backup.create",
}
PERMISSIONS: dict[str, set[str]] = {
    "owner": {"*"},
    "manager": _ALL_BUT_ADMIN,
    "cashier": {"products.view", "sales.create", "sales.view", "parties.view", "parties.edit", "payments.create"},
    "stock": {"products.view", "products.edit", "stock.adjust", "purchases.create", "purchases.view", "purchases.return",
              "parties.view", "parties.edit", "import.run", "export.run"},
    "accountant": {"products.view", "sales.view", "purchases.view", "parties.view", "payments.create",
                   "expenses.create", "reports.view", "accounts.view", "export.run", "day.close"},
}


def has_perm(role: str, perm: str) -> bool:
    p = PERMISSIONS.get(role, set())
    return "*" in p or perm in p


_bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)):
    from .models import User
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    try:
        data = jwt.decode(cred.credentials, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please login again")
    user = db.get(User, int(data["sub"]))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


def require(perm: str):
    def dep(user=Depends(current_user)):
        if not has_perm(user.role, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Not allowed: {perm}")
        return user
    return dep


class ApiError(HTTPException):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(code, msg)
