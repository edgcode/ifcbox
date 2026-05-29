"""App settings and shared paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env if present (does NOT override already-set env vars, so the
# test harness and shell exports win over the file).
load_dotenv()

DATA_DIR = Path(os.environ.get("IFCBOX_DATA_DIR", "data")).resolve()
# Local scratch cache for the cloud backend (downloaded blobs / staged uploads).
CACHE_DIR = Path(os.environ.get("IFCBOX_CACHE_DIR", "/tmp/ifcbox")).resolve()
API_PREFIX = "/api/v1"
