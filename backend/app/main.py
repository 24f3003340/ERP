import logging
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .core import APP_VERSION, BACKUP_DIR, SessionLocal, engine
from .models import Base, SchemaVersion
from .routers import accounts, admin, auth, parties, products, purchases, reports, sales
from .services import seed_accounts

log = logging.getLogger("erp")
SCHEMA_VERSION = 1


def init_db() -> None:
    """Create tables and record schema version. Future migrations append to MIGRATIONS (each runs once, after a backup)."""
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        cur = db.execute(select(SchemaVersion.version).order_by(SchemaVersion.version.desc()).limit(1)).scalar_one_or_none() or 0
        if cur < SCHEMA_VERSION:
            db.add(SchemaVersion(version=SCHEMA_VERSION))
        if db.execute(select(SchemaVersion)).first():
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


FRONT = Path(__file__).resolve().parents[2] / "frontend" / "dist"
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
