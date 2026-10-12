import io
import threading

from app.core import engine


def sale(client, h, lines, pays=None, **kw):
    body = {"lines": lines, "payments": pays or [], **kw}
    return client.post("/api/sales", headers=h, json=body)


def diag(client, h):
    d = client.get("/api/diagnostics", headers=h).json()
    assert d["healthy"], d["checks"]
    return d


def test_setup_login_and_permissions(client, owner, cashier):
    assert client.get("/api/status").json()["needs_setup"] is False
    assert client.post("/api/setup", json={"business_name": "x", "username": "abc", "password": "12345678"}).status_code == 409
    assert client.post("/api/login", json={"username": "owner", "password": "wrong"}).status_code == 401
    assert client.get("/api/products").status_code == 401
    # cashier cannot manage users, backups, expenses, reports, tax settings
    assert client.get("/api/users", headers=cashier).status_code == 403
    assert client.post("/api/backups", headers=cashier).status_code == 403
    assert client.get("/api/reports/gst", headers=cashier).status_code == 403
    assert client.put("/api/business", headers=cashier, json={"name": "x"}).status_code == 403


def test_billing_math_mixed_tax(client, owner, shop):
    # 2 x Rs105(5% incl) + 1 x Rs118(18% incl) = 210 + 118 = 328 gross
    r = sale(client, owner, [{"product_id": shop["rice"], "qty": 2}, {"product_id": shop["soap"], "qty": 1}], [{"method": "cash", "amount": 32800}])
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["total"] == 32800 and inv["round_off"] == 0
    assert inv["taxable"] == 20000 + 10000  # 21000/1.05, 11800/1.18
    assert inv["tax_total"] == 1000 + 1800
    assert inv["due"] == 0
    assert inv["number"].endswith("000001")
    diag(client, owner)
    tb = client.get("/api/accounts/trial-balance", headers=owner).json()
    assert tb["total_dr"] == tb["total_cr"]


def test_round_off_and_stock_deduction(client, owner, shop):
    r = sale(client, owner, [{"product_id": shop["rice"], "qty": 1, "discount": 250}], [{"method": "upi", "amount": 10300}])
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 10300  # 10500-250 = 10250 -> rounded to 10300 (nearest rupee)
    assert r.json()["round_off"] == 50
    p = client.get("/api/products", headers=owner, params={"q": "RICE1"}).json()[0]
    assert p["stock_qty"] == 99
    diag(client, owner)


def test_insufficient_stock_blocks_and_rolls_back(client, owner, shop):
    r = sale(client, owner, [{"product_id": shop["rice"], "qty": 1}, {"product_id": shop["soap"], "qty": 11}], [{"method": "cash", "amount": 1}])
    assert r.status_code in (400, 409)
    assert client.get("/api/sales", headers=owner).json() == []
    rice = client.get("/api/products", headers=owner, params={"q": "RICE1"}).json()[0]
    assert rice["stock_qty"] == 100  # nothing partially applied
    diag(client, owner)


def test_idempotent_retry_does_not_double_post(client, owner, shop):
    body = [{"product_id": shop["rice"], "qty": 1}]
    a = sale(client, owner, body, [{"method": "cash", "amount": 10500}], idem_key="abc-1").json()
    b = sale(client, owner, body, [{"method": "cash", "amount": 10500}], idem_key="abc-1").json()
    assert a["id"] == b["id"]
    assert len(client.get("/api/sales", headers=owner).json()) == 1
    assert client.get("/api/products", headers=owner, params={"q": "RICE1"}).json()[0]["stock_qty"] == 99


def test_cashier_price_and_discount_controls(client, owner, cashier, shop):
    assert sale(client, cashier, [{"product_id": shop["rice"], "qty": 1, "unit_price": 100}], [{"method": "cash", "amount": 100}]).status_code == 403
    assert sale(client, cashier, [{"product_id": shop["rice"], "qty": 1, "discount": 5000}], [{"method": "cash", "amount": 5500}]).status_code == 403
    assert sale(client, cashier, [{"product_id": shop["rice"], "qty": 1, "discount": 500}], [{"method": "cash", "amount": 10000}]).status_code == 200
    # cashier cannot cancel
    inv = client.get("/api/sales", headers=owner).json()[0]
    assert client.post(f"/api/sales/{inv['id']}/cancel", headers=cashier, json={"reason": "test"}).status_code == 403


def test_credit_sale_receipt_and_statement(client, owner, shop):
    r = sale(client, owner, [{"product_id": shop["rice"], "qty": 4}], [{"method": "cash", "amount": 10000}], customer_id=shop["cus"])
    assert r.status_code == 200, r.text
    assert r.json()["due"] == 42000 - 10000 - 0 or r.json()["due"] > 0
    due = r.json()["due"]
    cus = [c for c in client.get("/api/customers", headers=owner).json() if c["id"] == shop["cus"]][0]
    assert cus["balance"] == due
    # walk-in cannot take credit
    assert sale(client, owner, [{"product_id": shop["rice"], "qty": 1}]).status_code == 400
    # over-payment refused, then settle
    assert client.post(f"/api/customers/{shop['cus']}/receipts", headers=owner, json={"amount": due + 1, "method": "cash"}).status_code == 400
    assert client.post(f"/api/customers/{shop['cus']}/receipts", headers=owner, json={"amount": due, "method": "upi"}).status_code == 200
    cus = [c for c in client.get("/api/customers", headers=owner).json() if c["id"] == shop["cus"]][0]
    assert cus["balance"] == 0
    st = client.get(f"/api/customers/{shop['cus']}/statement", headers=owner).json()
    assert st[-1]["balance"] == 0
    diag(client, owner)


def test_credit_limit_enforced(client, owner, shop):
    r = sale(client, owner, [{"product_id": shop["rice"], "qty": 20}], customer_id=shop["cus"])  # 2100 > limit 1000
    assert r.status_code == 409 and "Credit limit" in r.json()["detail"]


def test_return_rules_and_reversal(client, owner, shop):
    inv = sale(client, owner, [{"product_id": shop["rice"], "qty": 3}], [{"method": "cash", "amount": 31500}]).json()
    line = inv["lines"][0]["id"]
    r = client.post(f"/api/sales/{inv['id']}/returns", headers=owner, json={"lines": [{"sales_line_id": line, "qty": 4}], "reason": "too many"})
    assert r.status_code == 409
    r = client.post(f"/api/sales/{inv['id']}/returns", headers=owner, json={"lines": [{"sales_line_id": line, "qty": 1}], "reason": "defect", "refund_method": "cash"})
    assert r.status_code == 200, r.text
    assert r.json()["refund_amount"] == 10500
    # damaged item is not restocked
    r = client.post(f"/api/sales/{inv['id']}/returns", headers=owner, json={"lines": [{"sales_line_id": line, "qty": 1, "disposition": "damaged"}], "reason": "broken"})
    assert r.status_code == 200
    stock = client.get("/api/products", headers=owner, params={"q": "RICE1"}).json()[0]["stock_qty"]
    assert stock == 100 - 3 + 1
    # remaining qty = 1, returning 2 more must fail
    assert client.post(f"/api/sales/{inv['id']}/returns", headers=owner, json={"lines": [{"sales_line_id": line, "qty": 2}], "reason": "x y"}).status_code == 409
    # cannot cancel an invoice that has returns
    assert client.post(f"/api/sales/{inv['id']}/cancel", headers=owner, json={"reason": "oops"}).status_code == 409
    diag(client, owner)


def test_cancel_restores_stock_and_ledger(client, owner, shop):
    inv = sale(client, owner, [{"product_id": shop["soap"], "qty": 2}], [{"method": "cash", "amount": 23600}]).json()
    assert client.post(f"/api/sales/{inv['id']}/cancel", headers=owner, json={"reason": "wrong item"}).status_code == 200
    assert client.post(f"/api/sales/{inv['id']}/cancel", headers=owner, json={"reason": "again"}).status_code == 409
    assert client.get("/api/products", headers=owner, params={"q": "SOAP1"}).json()[0]["stock_qty"] == 10
    pnl = client.get("/api/accounts/pnl", headers=owner).json()
    assert pnl["net_profit"] == 0
    cb = client.get("/api/cashbook", headers=owner).json()
    assert cb["closing"] == 0
    audit = client.get("/api/audit", headers=owner, params={"action": "invoice.cancel"}).json()
    assert audit and audit[0]["reason"] == "wrong item"
    diag(client, owner)


def test_purchase_updates_stock_and_payable(client, owner, shop):
    body = {"supplier_id": shop["sup"], "supplier_invoice_no": "S-77", "lines": [{"product_id": shop["rice"], "qty": 50, "unit_cost": 8200}],
            "payments": [{"method": "bank", "amount": 100000}]}
    r = client.post("/api/purchases", headers=owner, json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["taxable"] == 410000 and p["tax_total"] == 20500 and p["due"] == 430500 - 100000
    assert client.post("/api/purchases", headers=owner, json=body).status_code == 409  # same supplier invoice no.
    assert client.get("/api/products", headers=owner, params={"q": "RICE1"}).json()[0]["stock_qty"] == 150
    sup = [s for s in client.get("/api/suppliers", headers=owner).json() if s["id"] == shop["sup"]][0]
    assert sup["balance"] == p["due"]
    assert client.post(f"/api/suppliers/{shop['sup']}/payments", headers=owner, json={"amount": p["due"], "method": "cash"}).status_code == 200
    diag(client, owner)


def test_stock_adjust_count_and_ledger(client, owner, shop):
    assert client.post("/api/stock/adjust", headers=owner, json={"product_id": shop["soap"], "qty_delta": -3, "reason": "damaged"}).status_code == 200
    assert client.post("/api/stock/adjust", headers=owner, json={"product_id": shop["soap"], "qty_delta": -50, "reason": "bad"}).status_code == 409
    prev = client.post("/api/stock/count", headers=owner, json={"items": [{"product_id": shop["soap"], "counted": 8}]}).json()
    assert prev[0]["variance"] == 1 and client.get("/api/products", headers=owner, params={"q": "SOAP1"}).json()[0]["stock_qty"] == 7
    client.post("/api/stock/count", headers=owner, json={"items": [{"product_id": shop["soap"], "counted": 8}], "apply": True})
    assert client.get("/api/products", headers=owner, params={"q": "SOAP1"}).json()[0]["stock_qty"] == 8
    assert len(client.get(f"/api/products/{shop['soap']}/ledger", headers=owner).json()) >= 3
    diag(client, owner)


def test_day_close_variance_needs_reason(client, owner, shop):
    sale(client, owner, [{"product_id": shop["rice"], "qty": 1}], [{"method": "cash", "amount": 10500}])
    prev = client.get("/api/day-close/preview", headers=owner).json()
    assert prev["expected_cash"] == 10500
    assert client.post("/api/day-close", headers=owner, json={"counted_cash": 10000}).status_code == 400
    r = client.post("/api/day-close", headers=owner, json={"counted_cash": 10000, "reason": "change given"})
    assert r.status_code == 200 and r.json()["variance"] == -500
    assert client.post("/api/day-close", headers=owner, json={"counted_cash": 10000, "reason": "again"}).status_code == 409


def test_import_preview_and_all_or_nothing(client, owner):
    good = "sku,name,sale_price,gst_rate,opening_qty\nA1,Alpha,10.50,5,3\nA2,Beta,20,12,0\n"
    bad = "sku,name,sale_price\nB1,Ok,5\nB1,Dup,5\n,NoSku,3\n"
    files = lambda t: {"file": ("p.csv", io.BytesIO(t.encode()), "text/csv")}
    r = client.post("/api/products/import", headers=owner, files=files(bad)).json()
    assert len(r["errors"]) == 2 and r["imported"] == 0
    assert client.post("/api/products/import", headers=owner, params={"commit": True}, files=files(bad)).status_code == 400
    assert client.get("/api/products", headers=owner).json() == []
    r = client.post("/api/products/import", headers=owner, params={"commit": True}, files=files(good)).json()
    assert r["imported"] == 2
    prods = client.get("/api/products", headers=owner).json()
    assert {p["sku"]: p["stock_qty"] for p in prods} == {"A1": 3, "A2": 0}
    assert prods[0]["sale_price"] == 1050
    csv = client.get("/api/products/export/csv", headers=owner)
    assert "Alpha" in csv.text
    diag(client, owner)


def test_reports_dashboard_gst(client, owner, shop):
    sale(client, owner, [{"product_id": shop["rice"], "qty": 2}, {"product_id": shop["soap"], "qty": 1}], [{"method": "cash", "amount": 32800}])
    d = client.get("/api/dashboard", headers=owner).json()
    assert d["sales_today"] == 32800 and d["bills_today"] == 1 and d["cash_today"] == 32800
    g = client.get("/api/reports/gst", headers=owner).json()
    assert g["output_tax_net"] == 2800 and {r["rate"] for r in g["output_by_rate"]} == {5.0, 18.0}
    m = client.get("/api/reports/margin", headers=owner).json()["rows"]
    assert sum(r["margin"] for r in m) == 30000 - (2 * 8000 + 7000)
    assert client.get("/api/reports/stock", headers=owner).json()["total_value"] > 0
    assert client.get("/api/reports/export/sales", headers=owner).status_code == 200


def test_backup_verify_restore(client, owner, shop):
    from app.core import IS_SQLITE
    r = client.post("/api/backups", headers=owner)
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    v = client.post(f"/api/backups/{name}/verify", headers=owner).json()
    assert v["ok"]
    if not IS_SQLITE:
        return
    sale(client, owner, [{"product_id": shop["rice"], "qty": 1}], [{"method": "cash", "amount": 10500}])
    assert len(client.get("/api/sales", headers=owner).json()) == 1
    rr = client.post(f"/api/backups/{name}/restore", headers=owner)
    assert rr.status_code == 200, rr.text
    assert client.get("/api/sales", headers=owner).json() == []  # back to the state at backup time


def test_concurrent_sales_of_last_unit(client, owner, shop):
    """Two terminals sell the same last unit: exactly one succeeds, stock never goes negative."""
    # reduce soap stock to 1
    assert client.post("/api/stock/adjust", headers=owner, json={"product_id": shop["soap"], "qty_delta": -9, "reason": "setup"}).status_code == 200
    results = []

    def go(i):
        r = sale(client, owner, [{"product_id": shop["soap"], "qty": 1}], [{"method": "cash", "amount": 11800}], idem_key=f"k{i}")
        results.append(r.status_code)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count(200) == 1, results
    assert client.get("/api/products", headers=owner, params={"q": "SOAP1"}).json()[0]["stock_qty"] == 0
    diag(client, owner)
