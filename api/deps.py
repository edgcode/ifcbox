"""App settings and shared paths."""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("IFCBOX_DATA_DIR", "data")).resolve()
API_PREFIX = "/api/v1"
