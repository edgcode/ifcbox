"""Shared fixtures.

The test IFC (`ifcbox/model.ifc`) is gitignored and large; tests that need it
skip cleanly when it is absent. Floor preparation is expensive, so the engine
PreparedFloor is built once per session.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Force the local backend + an isolated data dir BEFORE any `api` module is
# imported, so a cloud .env never leaks into the test suite.
os.environ["IFCBOX_STORAGE"] = "local"
os.environ.setdefault("IFCBOX_DATA_DIR", tempfile.mkdtemp(prefix="ifcbox_test_"))

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_IFC = REPO_ROOT / "ifcbox" / "model.ifc"
TEST_FLOOR = 6   # OKFF OG1 — residential floor with apartments

# Pre-refactor reference route (Flur:1375428 → Bad:1375434), point→point.
BASELINE_LENGTH = 4.5
BASELINE_START_XYZ = (5.329, 41.773, 6.92)
BASELINE_END_XYZ = (9.311, 42.449, 6.92)


@pytest.fixture(scope="session")
def model_ifc_path() -> Path:
    if not MODEL_IFC.exists():
        pytest.skip(f"test IFC not found: {MODEL_IFC}")
    return MODEL_IFC


@pytest.fixture(scope="session")
def model(model_ifc_path):
    from ifcbox.pipeline.loader import load_model
    return load_model(str(model_ifc_path))


@pytest.fixture(scope="session")
def storey(model):
    from ifcbox.pipeline.loader import list_storeys
    return list_storeys(model)[TEST_FLOOR]


@pytest.fixture(scope="session")
def prepared_floor(model, storey):
    """Engine PreparedFloor for the test floor — built once."""
    from ifcbox.engine import prepare_floor
    return prepare_floor(model, storey, floor_index=TEST_FLOOR, model_id="test")
