"""Load realistic DUMMY data through the real API (for demos / pilot training).
Usage: python scripts/seed_demo.py [base_url]     (needs: pip install httpx)"""
import sys

import httpx

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
c = httpx.Client(base_url=base + "/api", timeout=30)
r = c.post("/setup", json={"business_name": "Sharma General Store", "username": "owner", "password": "owner12345", "full_name": "Rakesh Sharma",
                           "address": "12 Main Bazaar, Jaipur", "phone": "9876543210", "gstin": "08ABCDE1234F1Z5"})
if r.status_code == 409:
    r = c.post("/login", json={"username": "owner", "password": "owner12345"})
r.raise_for_status()
c.headers["Authorization"] = "Bearer " + r.json()["token"]

for u in ("cashier", "manager", "accountant"):
    c.post("/users", json={"username": u, "password": u + "12345", "role": u})

items = [("RICE5", "Basmati Rice 5kg", "Grocery", 52500, 42000, 5, 40), ("ATTA10", "Wheat Atta 10kg", "Grocery", 41000, 34000, 0, 30),
         ("OIL1", "Sunflower Oil 1L", "Grocery", 15500, 13200, 5, 60), ("SUGAR1", "Sugar 1kg", "Grocery", 4800, 4100, 5, 80),
         ("TEA250", "Tea Premium 250g", "Grocery", 14000, 11000, 5, 25), ("SOAP", "Bath Soap", "Personal care", 4500, 3000, 18, 100),
         ("SHAMP", "Shampoo 180ml", "Personal care", 19900, 14000, 18, 30), ("BISC", "Biscuits Family Pack", "Snacks", 3000, 2300, 18, 120),
         ("NOODLE", "Instant Noodles", "Snacks", 1400, 1050, 12, 200), ("PEN", "Ball Pen (10 pack)", "Stationery", 9000, 6000, 18, 15),
         ("NBOOK", "Notebook 200pg", "Stationery", 6000, 4000, 12, 50), ("BULB", "LED Bulb 9W", "Electrical", 12000, 8000, 12, 4)]
ids, price = {}, {}
for i, (sku, name, cat, sp, cost, gst, qty) in enumerate(items):
    p = c.post("/products", json=dict(sku=sku, name=name, category=cat, sale_price=sp, purchase_price=cost, gst_rate=gst, opening_qty=qty,
                                      reorder_level=10 if qty > 10 else 5, barcode=f"89010{i:05d}")).json()
    ids[sku], price[sku] = p["id"], sp
sup = c.post("/suppliers", json={"name": "Jaipur Wholesale Traders", "phone": "9811111111", "gstin": "08AAAAA0000A1Z5"}).json()
cus = [c.post("/customers", json={"name": n, "phone": ph, "credit_limit": lim}).json() for n, ph, lim in
       (("Ramesh Gupta", "9822200001", 500000), ("Sunita Devi", "9822200002", 200000), ("Mohan Kirana", "9822200003", 1000000))]
c.post("/purchases", json={"supplier_id": sup["id"], "supplier_invoice_no": "JW-1021",
                           "lines": [{"product_id": ids["RICE5"], "qty": 20, "unit_cost": 42000}, {"product_id": ids["OIL1"], "qty": 30, "unit_cost": 13200}],
                           "payments": [{"method": "bank", "amount": 500000}]}).raise_for_status()
# (items, payment method or None for full credit, customer)
for lines, method, cid in [([("RICE5", 1), ("OIL1", 2)], "cash", None), ([("SOAP", 3), ("SHAMP", 1)], "upi", None),
                           ([("NOODLE", 10), ("BISC", 4)], "cash", None), ([("ATTA10", 2), ("SUGAR1", 5)], None, cus[0]["id"]),
                           ([("PEN", 2), ("NBOOK", 5)], "card", None), ([("TEA250", 2)], "cash", cus[1]["id"])]:
    body = {"lines": [{"product_id": ids[s], "qty": q} for s, q in lines], "customer_id": cid, "payments": []}
    if method:
        total = sum(price[s] * q for s, q in lines)  # prices are GST-inclusive, so the bill is the sum rounded to a rupee
        body["payments"] = [{"method": method, "amount": round(total / 100) * 100}]
    r = c.post("/sales", json=body)
    if r.status_code != 200:  # e.g. rounding differences: retry as part-payment against the customer
        print("sale skipped:", r.text)
c.post("/expenses", json={"category": "Electricity", "amount": 250000, "method": "cash"})
print("Demo data loaded. Logins: owner/owner12345, manager/manager12345, cashier/cashier12345, accountant/accountant12345")
