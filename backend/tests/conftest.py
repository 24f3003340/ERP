import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="erp-test-")
os.environ["ERP_DATA_DIR"] = _tmp
os.environ.setdefault("ERP_DATABASE_URL", f"sqlite:///{_tmp}/test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import engine  # noqa: E402
from app.main import app, init_db  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    init_db()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def owner(client):
    r = client.post("/api/setup", json={"business_name": "Test Shop", "username": "owner", "password": "password123"})
    assert r.status_code == 200, r.text
    return _hdr(r.json()["token"])


@pytest.fixture()
def cashier(client, owner):
    assert client.post("/api/users", headers=owner, json={"username": "cash1", "password": "password123", "role": "cashier"}).status_code == 200
    r = client.post("/api/login", json={"username": "cash1", "password": "password123"})
    return _hdr(r.json()["token"])


@pytest.fixture()
def shop(client, owner):
    """Two products (5% and 18% GST), one supplier, one customer. Returns dict of ids."""
    def prod(sku, name, price, cost, gst, qty, **kw):
        r = client.post("/api/products", headers=owner, json=dict(sku=sku, name=name, sale_price=price, purchase_price=cost, gst_rate=gst,
                                                                    opening_qty=qty, reorder_level=5, **kw))
        assert r.status_code == 200, r.text
        return r.json()["id"]
    a = prod("RICE1", "Rice 1kg", 10500, 8000, 5, 100)           # Rs105 incl 5% GST
    b = prod("SOAP1", "Soap", 11800, 7000, 18, 10, barcode="890100")  # Rs118 incl 18% GST
    sup = client.post("/api/suppliers", headers=owner, json={"name": "Agro Traders"}).json()["id"]
    cus = client.post("/api/customers", headers=owner, json={"name": "Ramesh", "phone": "9999999999", "credit_limit": 100000}).json()["id"]
    return {"rice": a, "soap": b, "sup": sup, "cus": cus}
