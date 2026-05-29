"""Per-floor endpoints: detail, prepare (background), geometry, prep progress WS."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ifcbox.overlays import clearance_png, occupancy_png
from ifcbox.rooms import ROOM_CLASSES
from api import cache, tasks
from api.schemas import FloorDetail, GridMeta, SpaceOut, TerminalOut
from api.storage import blobs, meta
from api.storage import keys

router = APIRouter(tags=["floors"])


def _require_floor(model_id: str, n: int) -> dict:
    row = meta.get_model(model_id)
    if row is None:
        raise HTTPException(404, "model not found")
    if n < 0 or n >= row["storey_count"]:
        raise HTTPException(404, f"floor {n} out of range (0–{row['storey_count'] - 1})")
    model_meta = json.loads(blobs.read_text(keys.model_meta(model_id)))
    return model_meta["storeys"][n]


def _floor_status(model_id: str, n: int) -> str:
    row = meta.get_floor_prep(model_id, n)
    return row["status"] if row else "unprepared"


@router.get("/models/{model_id}/floors/{n}", response_model=FloorDetail)
async def floor_detail(model_id: str, n: int):
    storey = _require_floor(model_id, n)
    status = _floor_status(model_id, n)

    terminals: list[TerminalOut] = []
    spaces: list[SpaceOut] = []
    grid: GridMeta | None = None
    if status == "ready":
        prep = cache.get_prepared(model_id, n)
        if prep is not None:
            st = prep.site_transform
            terminals = [
                TerminalOut(id=gid,
                            xyz=tuple(float(c) for c in st.to_world(pos.reshape(1, 3))[0]))
                for gid, pos in prep.terminals.items()
            ]
            spaces = [
                SpaceOut(id=gid, name=s["name"],
                         centroid=tuple(float(c) for c in st.to_world(s["centroid"].reshape(1, 3))[0]))
                for gid, s in prep.spaces.items()
            ]
            grid = GridMeta(
                origin=(float(prep.meta.origin[0]), float(prep.meta.origin[1])),
                resolution=float(prep.meta.resolution),
                shape=(int(prep.meta.shape[0]), int(prep.meta.shape[1])),
                pipe_z=float(prep.pipe_z),
                site_to_world=prep.site_transform.inv_matrix.tolist(),
            )

    return FloorDetail(model_id=model_id, floor_index=n, name=storey["name"],
                       status=status, terminals=terminals, spaces=spaces, grid=grid)


@router.post("/models/{model_id}/floors/{n}/prepare", status_code=202)
async def prepare_floor_endpoint(model_id: str, n: int):
    _require_floor(model_id, n)
    status = _floor_status(model_id, n)
    if status in ("ready", "preparing"):
        return {"status": status}
    tasks.submit_prepare(model_id, n)
    return {"status": "preparing"}


@router.get("/models/{model_id}/floors/{n}/geometry")
async def floor_geometry(model_id: str, n: int):
    _require_floor(model_id, n)
    shell = blobs.read_path(keys.floor_shell(model_id, n))
    if _floor_status(model_id, n) != "ready" or shell is None:
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
    return FileResponse(shell, media_type="model/gltf-binary", filename="shell.glb")


@router.get("/room-classes")
async def room_classes():
    return [{"key": k, "label": label, "color": color} for k, label, color in ROOM_CLASSES]


@router.get("/models/{model_id}/floors/{n}/overlays/{kind}")
async def floor_overlay(model_id: str, n: int, kind: str):
    _require_floor(model_id, n)
    if kind not in ("occupancy", "clearance", "rooms"):
        raise HTTPException(404, "unknown overlay")

    # 'rooms' is rasterised at prepare time (needs space geometry) and served as a file.
    if kind == "rooms":
        path = blobs.read_path(keys.floor_rooms(model_id, n))
        if _floor_status(model_id, n) != "ready" or path is None:
            raise HTTPException(409, {"detail": "floor not prepared",
                                      "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
        return FileResponse(path, media_type="image/png")

    prep = cache.get_prepared(model_id, n)
    if prep is None:
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
    png = (occupancy_png(prep.occupancy) if kind == "occupancy"
           else clearance_png(prep.clearance, prep.occupancy))
    return Response(content=png, media_type="image/png")


@router.get("/models/{model_id}/floors/{n}/walls")
async def floor_walls(model_id: str, n: int):
    _require_floor(model_id, n)
    path = blobs.read_path(keys.floor_walls(model_id, n))
    if _floor_status(model_id, n) != "ready" or path is None:
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
    return FileResponse(path, media_type="application/json")


@router.get("/models/{model_id}/floors/{n}/apartments")
async def floor_apartments(model_id: str, n: int):
    _require_floor(model_id, n)
    if _floor_status(model_id, n) != "ready":
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
    path = blobs.read_path(keys.floor_apartments(model_id, n))
    if path is None:
        # Lazy backfill for floors prepared before apartments.json existed.
        from ifcbox.apartments import discover_apartments
        from ifcbox.pipeline.loader import list_storeys, load_model
        prep = cache.get_prepared(model_id, n)
        ifc = blobs.read_path(keys.model_ifc(model_id))
        if prep is None or ifc is None:
            raise HTTPException(409, {"detail": "floor not prepared"})
        model = load_model(ifc)
        storey = list_storeys(model)[n]
        apts = discover_apartments(model, storey, prep.site_transform)
        blobs.write_text(keys.floor_apartments(model_id, n), json.dumps(apts))
        blobs.commit(keys.floor_apartments(model_id, n))
        path = blobs.read_path(keys.floor_apartments(model_id, n))
    return FileResponse(path, media_type="application/json")


@router.websocket("/models/{model_id}/floors/{n}/prepare/ws")
async def prepare_ws(websocket: WebSocket, model_id: str, n: int):
    await websocket.accept()
    try:
        while True:
            row = meta.get_floor_prep(model_id, n)
            status = row["status"] if row else "unprepared"
            await websocket.send_json({
                "status": status,
                "stage": row["stage"] if row else "",
                "pct": row["pct"] if row else 0,
                "error": row["error"] if row else "",
            })
            if status in ("ready", "error"):
                break
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        pass
