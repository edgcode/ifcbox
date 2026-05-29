"""Routing endpoints: submit (sync), history, fetch, mesh, delete."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ifcbox.engine import build_route_mesh, route
from ifcbox.pipeline.export import export_gltf
from ifcbox.resolver import AnchorError
from api import cache
from api.schemas import RouteRequest
from api.storage import blobs, meta
from api.storage import keys

router = APIRouter(tags=["routes"])


@router.post("/models/{model_id}/floors/{n}/routes")
async def submit_route(model_id: str, n: int, req: RouteRequest):
    if meta.get_model(model_id) is None:
        raise HTTPException(404, "model not found")

    prep = cache.get_prepared(model_id, n)
    if prep is None:
        raise HTTPException(409, {"detail": "floor not prepared",
                                  "prepare_url": f"/api/v1/models/{model_id}/floors/{n}/prepare"})

    try:
        source = req.source.to_anchor()
        targets = [t.to_anchor() for t in req.targets]
    except ValueError as e:
        raise HTTPException(422, str(e))

    try:
        result = route(prep, source, targets, mode=req.mode, params=req.params.to_params())
    except AnchorError as e:
        raise HTTPException(422, str(e))

    route_id = "r_" + uuid.uuid4().hex[:12]
    blobs.write_text(keys.route_request(route_id), req.model_dump_json(indent=2))
    blobs.commit(keys.route_request(route_id))

    payload = result.to_dict() | {
        "route_id": route_id,
        "model_id": model_id,
        "floor_index": n,
        "mesh_url": f"/api/v1/routes/{route_id}/mesh",
    }
    blobs.write_text(keys.route_result(route_id), json.dumps(payload, indent=2))
    blobs.commit(keys.route_result(route_id))
    export_gltf(build_route_mesh(result), blobs.write_path(keys.route_mesh(route_id)))
    blobs.commit(keys.route_mesh(route_id))

    meta.insert_route(route_id, model_id, n, result.mode,
                      result.total_length, len(result.segments))
    return payload


@router.get("/models/{model_id}/routes")
async def list_routes(model_id: str):
    if meta.get_model(model_id) is None:
        raise HTTPException(404, "model not found")
    return [
        {"route_id": r["id"], "floor_index": r["floor_index"], "mode": r["mode"],
         "total_length_m": r["total_length"], "segment_count": r["segment_count"],
         "created_at": r["created_at"]}
        for r in meta.list_routes_for_model(model_id)
    ]


@router.get("/routes/{route_id}")
async def get_route(route_id: str):
    raw = blobs.read_text(keys.route_result(route_id))
    if raw is None:
        raise HTTPException(404, "route not found")
    return json.loads(raw)


@router.get("/routes/{route_id}/mesh")
async def get_route_mesh(route_id: str):
    mesh = blobs.read_path(keys.route_mesh(route_id))
    if mesh is None:
        raise HTTPException(404, "route mesh not found")
    return FileResponse(mesh, media_type="model/gltf-binary", filename="pipe.glb")


@router.delete("/routes/{route_id}")
async def delete_route(route_id: str):
    if meta.get_route(route_id) is None:
        raise HTTPException(404, "route not found")
    meta.delete_route(route_id)
    blobs.delete_prefix(keys.route_dir(route_id))
    return {"deleted": route_id}
