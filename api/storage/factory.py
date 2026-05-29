"""Select storage backends from IFCBOX_STORAGE (default 'local')."""

from __future__ import annotations

import os

from api.deps import DATA_DIR
from api.storage.base import BlobStore, MetaStore
from api.storage.local import LocalBlobStore, SqliteMeta

_MODE = os.environ.get("IFCBOX_STORAGE", "local")


def _make() -> tuple[BlobStore, MetaStore]:
    if _MODE == "cloud":
        # D-2: R2BlobStore + PostgresMeta
        from api.storage.cloud import make_cloud
        return make_cloud()
    return LocalBlobStore(DATA_DIR), SqliteMeta(DATA_DIR / "ifcbox.db")


blobs, meta = _make()
