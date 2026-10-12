from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core import PERMISSIONS, ROLES, ApiError, current_user, get_db, hash_password, make_token, require, verify_password
from ..models import Business, User
from ..schemas import BusinessIn, LoginIn, SetupIn, UserIn
from ..services import audit, get_business, seed_accounts, unwrap_integrity

router = APIRouter(prefix="/api", tags=["auth"])


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "active": u.active,
            "permissions": sorted(PERMISSIONS[u.role]) if u.role != "owner" else ["*"]}


def business_out(b: Business) -> dict:
    return {c.name: getattr(b, c.name) for c in Business.__table__.columns if c.name != "created_at"}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(User))
    b = db.execute(select(Business).limit(1)).scalar_one_or_none()
    return {"needs_setup": n == 0, "business_name": b.name if b else None, "locale": b.locale if b else "en"}


@router.post("/setup")
def setup(body: SetupIn, db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(User)):
        raise ApiError("Already set up", 409)
    db.add(Business(name=body.business_name, gstin=body.gstin, address=body.address, phone=body.phone))
    u = User(username=body.username.strip().lower(), full_name=body.full_name, role="owner",
             password_hash=hash_password(body.password))
    db.add(u)
    seed_accounts(db)
    db.flush()
    audit(db, u, "setup", "business")
    db.commit()
    return {"token": make_token(u.id, u.role), "user": user_out(u)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.username == body.username.strip().lower())).scalar_one_or_none()
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        raise ApiError("Wrong username or password", 401)
    audit(db, u, "login", "user", u.id)
    db.commit()
    return {"token": make_token(u.id, u.role), "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user": user_out(user), "business": business_out(get_business(db))}


@router.put("/business")
def update_business(body: BusinessIn, user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    b = get_business(db)
    before = business_out(b)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    audit(db, user, "settings.update", "business", b.id, before=before, after=business_out(b))
    db.commit()
    return business_out(b)


@router.get("/users")
def list_users(user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.execute(select(User).order_by(User.id)).scalars()]


@router.post("/users")
def create_user(body: UserIn, user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise ApiError("Unknown role")
    if not body.password:
        raise ApiError("Password required (min 8 chars)")
    u = User(username=body.username.strip().lower(), full_name=body.full_name, role=body.role, active=body.active,
             password_hash=hash_password(body.password))
    db.add(u)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise unwrap_integrity(e)
    audit(db, user, "user.create", "user", u.id, after={"username": u.username, "role": u.role})
    db.commit()
    return user_out(u)


@router.put("/users/{uid}")
def update_user(uid: int, body: UserIn, user: User = Depends(require("users.manage")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise ApiError("User not found", 404)
    if body.role not in ROLES:
        raise ApiError("Unknown role")
    if u.id == user.id and (body.role != "owner" or not body.active):
        raise ApiError("You cannot demote or deactivate yourself")
    before = {"role": u.role, "active": u.active}
    u.full_name, u.role, u.active = body.full_name, body.role, body.active
    if body.password:
        u.password_hash = hash_password(body.password)
    audit(db, user, "user.update" if before["role"] == u.role else "user.role_change", "user", u.id, before=before,
          after={"role": u.role, "active": u.active, "password_changed": bool(body.password)})
    db.commit()
    return user_out(u)
