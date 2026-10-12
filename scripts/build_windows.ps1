# Build the Windows installer (run on Windows, in PowerShell, from the repo root).
# Needs: Python 3.10+, Node 18+.  Output: desktop\release\Local ERP Setup *.exe
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt pyinstaller
Push-Location frontend; npm install; npm run build; Pop-Location
Push-Location backend
..\.venv\Scripts\pyinstaller --noconfirm --onedir --name erp-server --distpath ..\build\dist --workpath ..\build\work --specpath ..\build `
  --paths . --add-data "migrations;migrations" --add-data "..\frontend\dist;frontend_dist" `
  --collect-submodules uvicorn --collect-submodules alembic --hidden-import psycopg2 --hidden-import app.routers.admin server.py
Pop-Location
Push-Location desktop; npm install; npm run dist; Pop-Location
Write-Host "Installer is in desktop\release"
