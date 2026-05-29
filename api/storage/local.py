"""Local storage backend: filesystem blobs + SQLite metadata (dev / tests)."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import IO


class LocalBlobStore:
    """Maps keys directly to files under `root` (commits are no-ops)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def read_path(self, key: str) -> Path | None:
        p = self._p(key)
        return p if p.exists() else None

    def write_path(self, key: str) -> Path:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_text(self, key: str, text: str) -> None:
        self.write_path(key).write_text(text)

    def write_stream(self, key: str, fileobj: IO) -> None:
        with self.write_path(key).open("wb") as out:
            shutil.copyfileobj(fileobj, out)

    def read_text(self, key: str) -> str | None:
        p = self._p(key)
        return p.read_text() if p.exists() else None

    def commit(self, key: str) -> None:
        pass

    def read_dir(self, prefix: str) -> Path | None:
        d = self._p(prefix)
        return d if d.exists() else None

    def write_dir(self, prefix: str) -> Path:
        d = self._p(prefix)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def commit_dir(self, prefix: str) -> None:
        pass

    def delete_prefix(self, prefix: str) -> None:
        p = self._p(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


_SCHEMA = """
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
  status        TEXT,
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


class SqliteMeta:
    """SQLite metadata store; rows returned as plain dicts."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # ── models ────────────────────────────────────────────────────────────────
    def insert_model(self, model_id, filename, storey_count, unit_scale) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO models (id, filename, uploaded_at, storey_count, status, unit_scale)"
                " VALUES (?,?,?,?,?,?)",
                (model_id, filename, _now(), storey_count, "uploaded", unit_scale),
            )

    def get_model(self, model_id) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
            return dict(r) if r else None

    def list_models(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in
                    c.execute("SELECT * FROM models ORDER BY uploaded_at DESC").fetchall()]

    def delete_model(self, model_id) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM models WHERE id=?", (model_id,))
            c.execute("DELETE FROM floor_prep WHERE model_id=?", (model_id,))
            c.execute("DELETE FROM routes WHERE model_id=?", (model_id,))

    # ── floor prep ──────────────────────────────────────────────────────────────
    def set_floor_status(self, model_id, floor, status, *, stage="", pct=0,
                         resolution=None, error="") -> None:
        prepared_at = _now() if status == "ready" else None
        with self._conn() as c:
            c.execute(
                "INSERT INTO floor_prep (model_id, floor_index, status, stage, pct, resolution, prepared_at, error)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(model_id, floor_index) DO UPDATE SET"
                " status=excluded.status, stage=excluded.stage, pct=excluded.pct,"
                " resolution=COALESCE(excluded.resolution, floor_prep.resolution),"
                " prepared_at=excluded.prepared_at, error=excluded.error",
                (model_id, floor, status, stage, pct, resolution, prepared_at, error),
            )

    def get_floor_prep(self, model_id, floor) -> dict | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM floor_prep WHERE model_id=? AND floor_index=?",
                (model_id, floor),
            ).fetchone()
            return dict(r) if r else None

    # ── routes ────────────────────────────────────────────────────────────────
    def insert_route(self, route_id, model_id, floor, mode, total_length, segment_count) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO routes (id, model_id, floor_index, mode, total_length, segment_count, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (route_id, model_id, floor, mode, total_length, segment_count, _now()),
            )

    def get_route(self, route_id) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
            return dict(r) if r else None

    def list_routes_for_model(self, model_id) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM routes WHERE model_id=? ORDER BY created_at DESC",
                (model_id,),
            ).fetchall()]

    def delete_route(self, route_id) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM routes WHERE id=?", (route_id,))
