"""Background floor-preparation worker.

Prep is CPU-heavy (mesh tessellation), so it runs off the event loop in a
single-worker thread pool — builds are serialized (spec-api.md §5). Progress
is written to the floor_prep DB row; the WS endpoint and GET-status poll both
read it from there (no cross-thread asyncio bridging needed).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from ifcbox.engine import prepare_floor
from ifcbox.geometry import export_floor_shell
from ifcbox.pipeline.loader import extract_floor_geometry, list_storeys, load_model
from ifcbox.rooms import export_rooms_png
from api import cache
from api.storage import blobs, meta
from api.storage import keys

logger = logging.getLogger("ifcbox.api.tasks")

_executor = ThreadPoolExecutor(max_workers=1)   # serialize prep builds


def submit_prepare(model_id: str, floor: int, resolution: float = 0.1) -> None:
    meta.set_floor_status(model_id, floor, "preparing", stage="queued", pct=0,
                          resolution=resolution)
    _executor.submit(_prepare_worker, model_id, floor, resolution)


def _prepare_worker(model_id: str, floor: int, resolution: float) -> None:
    try:
        meta.set_floor_status(model_id, floor, "preparing", stage="extract_meshes",
                              pct=10, resolution=resolution)
        ifc = blobs.read_path(keys.model_ifc(model_id))
        model = load_model(ifc)
        storey = list_storeys(model)[floor]
        geom = extract_floor_geometry(model, storey)

        meta.set_floor_status(model_id, floor, "preparing", stage="voxelize",
                              pct=50, resolution=resolution)
        prep = prepare_floor(model, storey, floor_index=floor, model_id=model_id,
                             resolution=resolution, geom=geom)
        prep.save(blobs.write_dir(keys.floor_dir(model_id, floor)))
        blobs.commit_dir(keys.floor_dir(model_id, floor))
        cache.put_prepared(model_id, floor, prep)

        meta.set_floor_status(model_id, floor, "preparing", stage="shell_glb",
                              pct=85, resolution=resolution)
        export_floor_shell(geom, blobs.write_path(keys.floor_shell(model_id, floor)),
                           blobs.write_path(keys.floor_walls(model_id, floor)))
        blobs.commit(keys.floor_shell(model_id, floor))
        blobs.commit(keys.floor_walls(model_id, floor))
        export_rooms_png(model, prep.meta, prep.pipe_z, prep.site_transform,
                         blobs.write_path(keys.floor_rooms(model_id, floor)))
        blobs.commit(keys.floor_rooms(model_id, floor))

        meta.set_floor_status(model_id, floor, "ready", stage="done", pct=100,
                              resolution=resolution)
        logger.info("Prepared %s floor %d", model_id, floor)
    except Exception as e:
        logger.exception("Prep failed for %s floor %d", model_id, floor)
        meta.set_floor_status(model_id, floor, "error", stage="error", pct=0, error=str(e))
