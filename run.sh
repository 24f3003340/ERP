#!/usr/bin/env bash
# One-command start: creates venv, installs deps, builds the UI (first time) and starts the app.
# Usage: ./run.sh            -> SQLite (single PC)
#        ERP_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/erp ./run.sh   -> PostgreSQL (LAN mode)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
[ -d .venv ] || $PY -m venv .venv
. .venv/bin/activate
pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi
HOST=${ERP_HOST:-127.0.0.1}   # 127.0.0.1 = this PC only. Use 0.0.0.0 only for LAN mode behind a firewall.
PORT=${ERP_PORT:-8000}
echo "ERP running at  http://localhost:$PORT"
cd backend && exec uvicorn app.main:app --host "$HOST" --port "$PORT"
