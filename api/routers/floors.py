"""Per-floor endpoints: detail, prepare (background), geometry, prep progress WS."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ifcbox.overlays import clearance_png, occupancy_png
from api import cache, tasks
from api.schemas import FloorDetail, GridMeta, SpaceOut, TerminalOut
from api.store import db, files

router = APIRouter(tags=["floors"])


def _require_floor(model_id: str, n: int) -> dict:
    row = db.get_model(model_id)
    if row is None:
        raise HTTPException(404, "model not found")
    if n < 0 or n >= row["storey_count"]:
        raise HTTPException(404, f"floor {n} out of range (0–{row['storey_count'] - 1})")
    meta = json.loads(files.model_meta(model_id).read_text())
    return meta["storeys"][n]


def _floor_status(model_id: str, n: int) -> str:
    row = db.get_floor_prep(model_id, n)
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
    shell = files.floor_shell(model_id, n)
    if _floor_status(model_id, n) != "ready" or not shell.exists():
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
    return FileResponse(shell, media_type="model/gltf-binary", filename="shell.glb")


@router.get("/models/{model_id}/floors/{n}/overlays/{kind}")
async def floor_overlay(model_id: str, n: int, kind: str):
    _require_floor(model_id, n)
    if kind not in ("occupancy", "clearance"):
        raise HTTPException(404, "unknown overlay")
    prep = cache.get_prepared(model_id, n)
    if prep is None:
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})
    png = (occupancy_png(prep.occupancy) if kind == "occupancy"
           else clearance_png(prep.clearance, prep.occupancy))
    return Response(content=png, media_type="image/png")


@router.websocket("/models/{model_id}/floors/{n}/prepare/ws")
async def prepare_ws(websocket: WebSocket, model_id: str, n: int):
    await websocket.accept()
    try:
        while True:
            row = db.get_floor_prep(model_id, n)
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
