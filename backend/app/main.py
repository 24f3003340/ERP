import logging
import os
import sys
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select

from .core import APP_VERSION, BACKUP_DIR, SessionLocal, engine
from .models import Base, SchemaVersion
from .routers import accounts, admin, auth, parties, products, purchases, reports, sales
from .services import seed_accounts

log = logging.getLogger("erp")
SCHEMA_VERSION = 2


# Works both from source and when frozen by PyInstaller (resources are unpacked under sys._MEIPASS).
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
MIGRATIONS_DIR = BASE / "migrations"


def _alembic_cfg():
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def run_migrations() -> None:
    """Apply pending Alembic migrations. An existing installation is backed up first."""
    from alembic import command
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    cfg = _alembic_cfg()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        has_data = "users" in inspect(conn).get_table_names()
    if current != head and has_data:
        log.warning("pending migration %s -> %s: taking pre-migration backup", current, head)
        admin.make_backup("pre-migration")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def init_db() -> None:
    run_migrations()
    Base.metadata.create_all(engine)  # safety net for any table not covered by a migration
    with SessionLocal() as db:
        if db.execute(select(SchemaVersion)).first() is None:
            db.add(SchemaVersion(version=SCHEMA_VERSION))
        seed_accounts(db)
        db.commit()


def _auto_backup_loop() -> None:
    while True:
        try:
            stamp = date.today().strftime("%Y%m%d")
            if not list(BACKUP_DIR.glob(f"erp-auto-{stamp}-*")):
                with SessionLocal() as db:
                    from .models import User
                    has_data = db.execute(select(User.id).limit(1)).first() is not None
                if has_data:
                    admin.make_backup("auto")
                    log.info("automatic backup created")
        except Exception:
            log.exception("automatic backup failed")
        time.sleep(3600)


app = FastAPI(title="Local ERP", version=APP_VERSION)


@app.on_event("startup")
def _startup():
    init_db()
    threading.Thread(target=_auto_backup_loop, daemon=True).start()


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    msgs = [f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return JSONResponse({"detail": "; ".join(msgs)}, status_code=422)


for r in (auth, products, parties, sales, purchases, accounts, reports, admin):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION}


FRONT = Path(os.environ.get("ERP_FRONTEND_DIR") or (BASE / "frontend_dist" if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if FRONT.exists():
    app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (FRONT / path).resolve()
        if path and f.is_file() and FRONT in f.parents:
            return FileResponse(f)
        return FileResponse(FRONT / "index.html")
