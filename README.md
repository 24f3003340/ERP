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
25 tests: billing math (mixed GST), atomic stock, idempotent retry, permissions, credit limit, returns, cancel/reversal, purchases, day close, CSV import rollback, backup/restore, concurrent sale of last unit, ledger balance.

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
| Backup (auto daily + manual, optional AES encryption), verify, restore (SQLite + PostgreSQL), diagnostics | ✅ |
| CSV product import with preview, errors and all-or-nothing rollback | ✅ |
| Hindi/English labels, INR formatting | ✅ (menu/dashboard; baaki screens English) |

## Desktop app (Electron) aur Windows installer
`desktop/` mein Electron shell hai: ye local server khud start karta hai, data `%APPDATA%\\Local ERP\\data` mein rakhta hai (install folder mein nahi, isliye upgrade/uninstall data nahi chhoone), aur hardened hai (contextIsolation, sandbox, CSP, navigation blocked).
```bash
cd desktop && npm install && npm start        # dev: repo ke .venv wale backend ke saath window kholta hai
```
Windows installer (`.exe`) Windows par banta hai: `scripts/build_windows.ps1` chalayein, ya GitHub → Actions → **Windows installer** → *Run workflow* (artifact download karein).

## Backup encryption
`ERP_BACKUP_PASSPHRASE="aapka-lamba-passphrase"` set karke app chalayein — har backup AES (Fernet, PBKDF2) se encrypt hota hai (`.enc`). Passphrase kho gaya to backup restore nahi hoga. Restore/verify ke time wahi passphrase set hona chahiye. Restore ab SQLite aur PostgreSQL (`pg_restore`) dono ke liye UI se hota hai; restore se pehle current data ka safety backup bante hai.

## Migrations
Schema ab Alembic se chalta hai (`backend/migrations/`). Purani install par app start hone par pending migration lagti hai, aur usse pehle automatic `pre-migration` backup banta hai.

## Day close lock, IGST, purchase return
- Din close hone ke baad us din naye bill / purchase / expense / payment / cancel / return block ho jaate hain (HTTP 423). Sirf owner reason ke saath "Reopen day" kar sakta hai (audit log mein).
- Business aur customer/supplier ka 2-digit state code alag ho to invoice **IGST** hota hai, warna CGST+SGST. GST report mein dono alag dikhte hain.
- Purchase cancel (stock/payable/payment reverse) aur supplier return (qty-limited, payable ghatata hai ya refund leta hai).

## Jo abhi bhi nahi hai (honest list)
- **E-invoice / IRN / GST return filing**: official GSTN/NIC portal ya GSP integration aur credentials chahiye; ye app generate nahi karta. GST summary sirf internal hai — CA se verify karwayein.
- Windows installer is repo mein **build-ready** hai, par maine Linux par hi test kiya hai (Electron shell + packaged server chale); `.exe` Windows par ek baar build karke test karna baaki hai. Code signing nahi hai (SmartScreen warning aayegi).
- Multi-branch, pharmacy batch/expiry, loyalty, e-commerce, AI — blueprint ke P2/later phases.
- Pilot (2–5 shops), CA/legal review aur real printer testing — ye insaan/hardware ka kaam hai.

## Design notes
- Paise (integer) mein paisa store hota hai; float nahi. Line-level tax/taxable invoice mein freeze hota hai.
- Posted invoices kabhi edit/delete nahi hote — cancel/return/adjustment se reverse hota hai.
- Stock update `UPDATE … WHERE stock_qty + delta >= 0` se atomic hai (SQLite aur PostgreSQL dono par), isliye do counters same last item nahi bech sakte.
- API localhost par bind hota hai (`127.0.0.1`) jab tak aap `ERP_HOST` na badlein. JWT secret `~/.local-erp/secret.key` mein auto-generate hota hai.
