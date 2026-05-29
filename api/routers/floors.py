"""Per-floor endpoints: detail, prepare (background), geometry, prep progress WS."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from api import cache, tasks
from api.schemas import FloorDetail, SpaceOut, TerminalOut
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

    return FloorDetail(model_id=model_id, floor_index=n, name=storey["name"],
                       status=status, terminals=terminals, spaces=spaces)


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
