"""Load realistic DUMMY data into a running server. Usage: python scripts/seed_demo.py [base_url] [password]   (needs httpx)"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.demo import seed  # noqa: E402

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
pw = sys.argv[2] if len(sys.argv) > 2 else "owner12345"
seed(httpx.Client(base_url=base, timeout=30), pw)
print(f"Demo data loaded. Users: owner, manager, cashier, accountant  (password: {pw})")
