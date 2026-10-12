"""Entry point for the packaged (PyInstaller) server used by the desktop app."""
import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("ERP_HOST", "127.0.0.1"), port=int(os.environ.get("ERP_PORT", "8000")), log_level="warning")
