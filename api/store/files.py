"""On-disk layout helpers. See plans/spec-api.md §3.2."""

from __future__ import annotations

from pathlib import Path

from api.deps import DATA_DIR


def db_path() -> Path:
    return DATA_DIR / "ifcbox.db"


# ── models ──────────────────────────────────────────────────────────────────
def model_dir(model_id: str) -> Path:
    return DATA_DIR / "models" / model_id


def model_ifc(model_id: str) -> Path:
    return model_dir(model_id) / "original.ifc"


def model_meta(model_id: str) -> Path:
    return model_dir(model_id) / "meta.json"


def floor_dir(model_id: str, n: int) -> Path:
    return model_dir(model_id) / "floors" / str(n)


def floor_shell(model_id: str, n: int) -> Path:
    return floor_dir(model_id, n) / "shell.glb"


def floor_walls(model_id: str, n: int) -> Path:
    return floor_dir(model_id, n) / "walls.json"


# ── routes ──────────────────────────────────────────────────────────────────
def route_dir(route_id: str) -> Path:
    return DATA_DIR / "routes" / route_id


def route_request(route_id: str) -> Path:
    return route_dir(route_id) / "request.json"


def route_result(route_id: str) -> Path:
    return route_dir(route_id) / "route.json"


def route_mesh(route_id: str) -> Path:
    return route_dir(route_id) / "pipe.glb"
