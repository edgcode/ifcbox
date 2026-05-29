"""Cloud storage backend: Cloudflare R2 blobs + Postgres metadata (prod).

R2BlobStore stages reads/writes through a local cache dir: read downloads on
miss, write stages locally and `commit` / `commit_dir` upload. This keeps the
path-oriented BlobStore contract working with libraries that need real files.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from api.deps import CACHE_DIR


# ── R2 (S3-compatible) ────────────────────────────────────────────────────────
class R2BlobStore:
    def __init__(self, *, bucket: str, endpoint: str, access_key: str, secret: str,
                 cache_dir: Path):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.cache_dir = Path(cache_dir)
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    def _cache(self, key: str) -> Path:
        return self.cache_dir / key

    def _list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def read_path(self, key: str) -> Path | None:
        from botocore.exceptions import ClientError
        cache = self._cache(key)
        if cache.exists():
            return cache
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, key, str(cache))
        except ClientError:
            return None
        return cache

    def write_path(self, key: str) -> Path:
        p = self._cache(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_text(self, key: str, text: str) -> None:
        self.write_path(key).write_text(text)

    def write_stream(self, key: str, fileobj: IO) -> None:
        with self.write_path(key).open("wb") as out:
            shutil.copyfileobj(fileobj, out)

    def read_text(self, key: str) -> str | None:
        p = self.read_path(key)
        return p.read_text() if p else None

    def commit(self, key: str) -> None:
        cache = self._cache(key)
        if cache.exists():
            self.client.upload_file(str(cache), self.bucket, key)

    def read_dir(self, prefix: str) -> Path | None:
        listed = self._list(prefix.rstrip("/") + "/")
        if not listed:
            return None
        for k in listed:
            dst = self.cache_dir / k
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                self.client.download_file(self.bucket, k, str(dst))
        return self.cache_dir / prefix

    def write_dir(self, prefix: str) -> Path:
        d = self.cache_dir / prefix
        d.mkdir(parents=True, exist_ok=True)
        return d

    def commit_dir(self, prefix: str) -> None:
        base = self.cache_dir / prefix
        for f in base.rglob("*"):
            if f.is_file():
                key = f.relative_to(self.cache_dir).as_posix()
                self.client.upload_file(str(f), self.bucket, key)

    def delete_prefix(self, prefix: str) -> None:
        keys = self._list(prefix.rstrip("/") + "/")
        if self.exists(prefix):
            keys.append(prefix)
        for i in range(0, len(keys), 1000):
            batch = keys[i:i + 1000]
            if batch:
                self.client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch]},
                )
        shutil.rmtree(self.cache_dir / prefix, ignore_errors=True)


# ── Postgres ──────────────────────────────────────────────────────────────────
_PG_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS models (
        id TEXT PRIMARY KEY, filename TEXT, uploaded_at TEXT,
        storey_count INTEGER, status TEXT, unit_scale DOUBLE PRECISION)""",
    """CREATE TABLE IF NOT EXISTS floor_prep (
        model_id TEXT, floor_index INTEGER, status TEXT, stage TEXT, pct INTEGER,
        resolution DOUBLE PRECISION, prepared_at TEXT, error TEXT,
        PRIMARY KEY (model_id, floor_index))""",
    """CREATE TABLE IF NOT EXISTS routes (
        id TEXT PRIMARY KEY, model_id TEXT, floor_index INTEGER, mode TEXT,
        total_length DOUBLE PRECISION, segment_count INTEGER, created_at TEXT)""",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresMeta:
    def __init__(self, dsn: str):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(
            conninfo=dsn, min_size=0, max_size=4, open=True,
            kwargs={"row_factory": dict_row},
        )

    def init(self) -> None:
        with self.pool.connection() as c:
            for stmt in _PG_SCHEMA:
                c.execute(stmt)

    def clear_preparing(self) -> None:
        with self.pool.connection() as c:
            c.execute("UPDATE floor_prep SET status='unprepared' WHERE status='preparing'")

    # ── models ────────────────────────────────────────────────────────────────
    def insert_model(self, model_id, filename, storey_count, unit_scale) -> None:
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO models (id, filename, uploaded_at, storey_count, status, unit_scale)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                (model_id, filename, _now(), storey_count, "uploaded", unit_scale),
            )

    def get_model(self, model_id) -> dict | None:
        with self.pool.connection() as c:
            return c.execute("SELECT * FROM models WHERE id=%s", (model_id,)).fetchone()

    def list_models(self) -> list[dict]:
        with self.pool.connection() as c:
            return c.execute("SELECT * FROM models ORDER BY uploaded_at DESC").fetchall()

    def delete_model(self, model_id) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM models WHERE id=%s", (model_id,))
            c.execute("DELETE FROM floor_prep WHERE model_id=%s", (model_id,))
            c.execute("DELETE FROM routes WHERE model_id=%s", (model_id,))

    # ── floor prep ──────────────────────────────────────────────────────────────
    def set_floor_status(self, model_id, floor, status, *, stage="", pct=0,
                         resolution=None, error="") -> None:
        prepared_at = _now() if status == "ready" else None
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO floor_prep (model_id, floor_index, status, stage, pct, resolution, prepared_at, error)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (model_id, floor_index) DO UPDATE SET"
                " status=EXCLUDED.status, stage=EXCLUDED.stage, pct=EXCLUDED.pct,"
                " resolution=COALESCE(EXCLUDED.resolution, floor_prep.resolution),"
                " prepared_at=EXCLUDED.prepared_at, error=EXCLUDED.error",
                (model_id, floor, status, stage, pct, resolution, prepared_at, error),
            )

    def get_floor_prep(self, model_id, floor) -> dict | None:
        with self.pool.connection() as c:
            return c.execute(
                "SELECT * FROM floor_prep WHERE model_id=%s AND floor_index=%s",
                (model_id, floor),
            ).fetchone()

    # ── routes ────────────────────────────────────────────────────────────────
    def insert_route(self, route_id, model_id, floor, mode, total_length, segment_count) -> None:
        with self.pool.connection() as c:
            c.execute(
                "INSERT INTO routes (id, model_id, floor_index, mode, total_length, segment_count, created_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (route_id, model_id, floor, mode, total_length, segment_count, _now()),
            )

    def get_route(self, route_id) -> dict | None:
        with self.pool.connection() as c:
            return c.execute("SELECT * FROM routes WHERE id=%s", (route_id,)).fetchone()

    def list_routes_for_model(self, model_id) -> list[dict]:
        with self.pool.connection() as c:
            return c.execute(
                "SELECT * FROM routes WHERE model_id=%s ORDER BY created_at DESC",
                (model_id,),
            ).fetchall()

    def delete_route(self, route_id) -> None:
        with self.pool.connection() as c:
            c.execute("DELETE FROM routes WHERE id=%s", (route_id,))


def make_cloud():
    store = R2BlobStore(
        bucket=os.environ["R2_BUCKET"],
        endpoint=os.environ["R2_ENDPOINT_URL"],
        access_key=os.environ["R2_ACCESS_KEY_ID"],
        secret=os.environ["R2_SECRET_ACCESS_KEY"],
        cache_dir=CACHE_DIR,
    )
    return store, PostgresMeta(os.environ["DATABASE_URL"])
