"""Application settings, read from environment variables with sane defaults."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'geo.db'}")

# Upload limits
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UNZIPPED_MB = int(os.getenv("MAX_UNZIPPED_MB", "500"))  # zip-bomb guard
MAX_ZIP_ENTRIES = int(os.getenv("MAX_ZIP_ENTRIES", "200"))

ALLOWED_EXTENSIONS = {".zip", ".kml"}

# File statuses
STATUS_PROCESSING = "PROCESSING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
