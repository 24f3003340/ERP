# Local ERP — local-first billing, stock & accounts

Blueprint (PDF) ke hisaab se bana **general-retail local-first ERP**: internet ke bina chalta hai, data aapke apne computer par rehta hai.

**Stack:** React + TypeScript (UI) · Python FastAPI (local API) · SQLite (single PC) / PostgreSQL (LAN, multi-counter)

## Local par chalane ka tareeka

Zaroori: Python 3.10+, Node 18+ (sirf pehli baar UI build ke liye).

```bash
git clone https://github.com/24f3003340/ERP && cd ERP
git checkout ccr-eda3830c-ogzgzj
./run.sh
```

Phir browser mein kholein: **http://localhost:8000**

Pehli baar "First-time setup" screen aayegi — shop ka naam aur owner ka username/password banayein.
Dummy data ke saath try karna ho to (server chalte hue, doosre terminal mein):

```bash
.venv/bin/python scripts/seed_demo.py     # logins: owner/owner12345, cashier/cashier12345 ...
```

Data `~/.local-erp/` mein rehta hai (database `erp.db`, `backups/`). Badalne ke liye `ERP_DATA_DIR`.

### Real PostgreSQL se connect karna (multi-counter / LAN mode)

```bash
docker compose up -d          # ya apna PostgreSQL 14+ server
ERP_DATABASE_URL=postgresql+psycopg2://erp:erp_pass@localhost:5432/erp ./run.sh
```

Tables pehli run par apne aap ban jaate hain. LAN ke liye `ERP_HOST=0.0.0.0` set karein — sirf private network + firewall ke peeche; PostgreSQL port workstations par expose na karein.
`ERP_DATABASE_URL` set na ho to SQLite use hota hai.

### Development mode
```bash
cd backend && ../.venv/bin/uvicorn app.main:app --reload      # API :8000
cd frontend && npm run dev                                    # UI :5173 (API ko proxy karta hai)
```

## Tests
```bash
cd backend && ../.venv/bin/python -m pytest -q                                  # SQLite
ERP_DATABASE_URL=postgresql+psycopg2://erp:erp_pass@localhost:5432/erp_test ../.venv/bin/python -m pytest -q   # PostgreSQL
```
17 tests: billing math (mixed GST), atomic stock, idempotent retry, permissions, credit limit, returns, cancel/reversal, purchases, day close, CSV import rollback, backup/restore, concurrent sale of last unit, ledger balance.

## Kya-kya hai (blueprint ke mutabiq)

| Module | Status |
|---|---|
| Login, roles (owner / manager / cashier / stock / accountant), backend permission checks | ✅ |
| Product master, barcode, GST, opening stock, stock ledger, stock adjustment, physical count + variance | ✅ |
| POS billing: barcode/keyboard-first, split payments, credit sale, hold/recall, F2/F8/F9, A4 & 80mm print, reprint marker | ✅ |
| Invoice numbering per financial year, idempotency key (double-click/retry safe), atomic invoice+stock+payment+journal | ✅ |
| Returns (against original invoice, qty-limited, restock/damaged), invoice cancel by reversal (never delete) | ✅ |
| Purchases (supplier invoice, GST input, stock increase, payable), supplier payments | ✅ |
| Customers/suppliers, credit limit, statements, receipts allocated oldest-first | ✅ |
| Expenses, cashbook, UPI/bank book, day close with variance reason | ✅ |
| Double-entry ledger, trial balance, P&L | ✅ |
| Reports: sales, margin, stock valuation, receivables/payables, GST summary; CSV exports | ✅ |
| Audit log (price override, cancel, reprint, adjustment, role change, backup, export, import) | ✅ |
| Backup (auto daily + manual), verify, restore (SQLite), diagnostics & integrity checks | ✅ |
| CSV product import with preview, errors and all-or-nothing rollback | ✅ |
| Hindi/English labels, INR formatting | ✅ (menu/dashboard; baaki screens English) |

## Jo abhi nahi hai (honest list)
- **Electron desktop shell / Windows installer** — abhi browser-based (localhost). Electron wrapper agla step hai.
- Supplier (purchase) return aur purchase cancel; multi-branch, pharmacy batch/expiry, loyalty, e-commerce, AI — blueprint ke P2/later phases.
- **E-invoice / IRN / GST return filing nahi hai.** GST summary sirf internal hai; CA se verify karwayein. Intra-state (CGST+SGST) maana gaya hai; inter-state IGST abhi nahi.
- Day close sirf record + variance karta hai; closed din mein naye bills block nahi karta.
- Backup encryption nahi; PostgreSQL ka restore admin `pg_restore` se karta hai (backup `pg_dump` se banta hai, UI se verify hota hai).
- Schema migrations abhi `create_all` + version table; Alembic baad mein jodna hai.
- Pilot (2–5 shops), CA/legal review aur printer testing real hardware par baaki hai.

## Design notes
- Paise (integer) mein paisa store hota hai; float nahi. Line-level tax/taxable invoice mein freeze hota hai.
- Posted invoices kabhi edit/delete nahi hote — cancel/return/adjustment se reverse hota hai.
- Stock update `UPDATE … WHERE stock_qty + delta >= 0` se atomic hai (SQLite aur PostgreSQL dono par), isliye do counters same last item nahi bech sakte.
- API localhost par bind hota hai (`127.0.0.1`) jab tak aap `ERP_HOST` na badlein. JWT secret `~/.local-erp/secret.key` mein auto-generate hota hai.
