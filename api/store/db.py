"""SQLite index/metadata store. Holds no array data — see plans/spec-api.md §3.3."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from api.store import files

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
  id            TEXT PRIMARY KEY,
  filename      TEXT,
  uploaded_at   TEXT,
  storey_count  INTEGER,
  status        TEXT,
  unit_scale    REAL
);
CREATE TABLE IF NOT EXISTS floor_prep (
  model_id      TEXT,
  floor_index   INTEGER,
  status        TEXT,        -- unprepared | preparing | ready | error
  stage         TEXT,
  pct           INTEGER,
  resolution    REAL,
  prepared_at   TEXT,
  error         TEXT,
  PRIMARY KEY (model_id, floor_index)
);
CREATE TABLE IF NOT EXISTS routes (
  id            TEXT PRIMARY KEY,
  model_id      TEXT,
  floor_index   INTEGER,
  mode          TEXT,
  total_length  REAL,
  segment_count INTEGER,
  created_at    TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    files.db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(files.db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── models ──────────────────────────────────────────────────────────────────
def insert_model(model_id: str, filename: str, storey_count: int, unit_scale: float) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO models (id, filename, uploaded_at, storey_count, status, unit_scale)"
            " VALUES (?,?,?,?,?,?)",
            (model_id, filename, _now(), storey_count, "uploaded", unit_scale),
        )


def get_model(model_id: str):
    with connect() as c:
        return c.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()


def list_models():
    with connect() as c:
        return c.execute("SELECT * FROM models ORDER BY uploaded_at DESC").fetchall()


def delete_model(model_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM models WHERE id=?", (model_id,))
        c.execute("DELETE FROM floor_prep WHERE model_id=?", (model_id,))
        c.execute("DELETE FROM routes WHERE model_id=?", (model_id,))


# ── floor prep ────────────────────────────────────────────────────────────────
def set_floor_status(model_id: str, floor: int, status: str, *, stage: str = "",
                     pct: int = 0, resolution: float | None = None,
                     error: str = "") -> None:
    prepared_at = _now() if status == "ready" else None
    with connect() as c:
        c.execute(
            "INSERT INTO floor_prep (model_id, floor_index, status, stage, pct, resolution, prepared_at, error)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(model_id, floor_index) DO UPDATE SET"
            " status=excluded.status, stage=excluded.stage, pct=excluded.pct,"
            " resolution=COALESCE(excluded.resolution, floor_prep.resolution),"
            " prepared_at=excluded.prepared_at, error=excluded.error",
            (model_id, floor, status, stage, pct, resolution, prepared_at, error),
        )


def get_floor_prep(model_id: str, floor: int):
    with connect() as c:
        return c.execute(
            "SELECT * FROM floor_prep WHERE model_id=? AND floor_index=?",
            (model_id, floor),
        ).fetchone()


# ── routes ────────────────────────────────────────────────────────────────────
def insert_route(route_id: str, model_id: str, floor: int, mode: str,
                 total_length: float, segment_count: int) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO routes (id, model_id, floor_index, mode, total_length, segment_count, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (route_id, model_id, floor, mode, total_length, segment_count, _now()),
        )


def get_route(route_id: str):
    with connect() as c:
        return c.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()


def list_routes_for_model(model_id: str):
    with connect() as c:
        return c.execute(
            "SELECT * FROM routes WHERE model_id=? ORDER BY created_at DESC",
            (model_id,),
        ).fetchall()


def delete_route(route_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM routes WHERE id=?", (route_id,))
