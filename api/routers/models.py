"""Model upload and lifecycle endpoints."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, UploadFile

from ifcbox.pipeline.loader import _length_unit_scale, list_storeys, load_model
from api import cache
from api.schemas import ModelOut, StoreyOut
from api.storage import blobs, meta
from api.storage import keys

router = APIRouter(tags=["models"])


def _storeys_from_meta(model_id: str) -> list[StoreyOut]:
    raw = blobs.read_text(keys.model_meta(model_id))
    return [StoreyOut(**s) for s in json.loads(raw)["storeys"]]


@router.post("/models", response_model=ModelOut)
async def upload_model(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".ifc"):
        raise HTTPException(422, "expected a .ifc file")

    model_id = uuid.uuid4().hex[:12]
    blobs.write_stream(keys.model_ifc(model_id), file.file)
    blobs.commit(keys.model_ifc(model_id))

    try:
        model = load_model(blobs.read_path(keys.model_ifc(model_id)))
        storeys = list_storeys(model)
        unit_scale = _length_unit_scale(model)
    except Exception as e:
        blobs.delete_prefix(keys.model_dir(model_id))
        raise HTTPException(422, f"could not parse IFC: {e}")

    storeys_out = [
        StoreyOut(index=i, name=s.name, elevation=s.elevation, height=s.height)
        for i, s in enumerate(storeys)
    ]
    blobs.write_text(keys.model_meta(model_id), json.dumps({
        "filename": file.filename,
        "unit_scale": unit_scale,
        "storeys": [s.model_dump() for s in storeys_out],
    }))
    blobs.commit(keys.model_meta(model_id))
    meta.insert_model(model_id, file.filename, len(storeys), unit_scale)

    return ModelOut(model_id=model_id, filename=file.filename,
                    storey_count=len(storeys), status="uploaded", storeys=storeys_out)


@router.get("/models")
async def list_models():
    return [
        {"model_id": r["id"], "filename": r["filename"],
         "storey_count": r["storey_count"], "status": r["status"],
         "uploaded_at": r["uploaded_at"]}
        for r in meta.list_models()
    ]


@router.get("/models/{model_id}", response_model=ModelOut)
async def get_model(model_id: str):
    row = meta.get_model(model_id)
    if row is None:
        raise HTTPException(404, "model not found")
    return ModelOut(
        model_id=row["id"], filename=row["filename"],
        storey_count=row["storey_count"], status=row["status"],
        storeys=_storeys_from_meta(model_id),
    )


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    if meta.get_model(model_id) is None:
        raise HTTPException(404, "model not found")
    meta.delete_model(model_id)
    cache.evict_model(model_id)
    blobs.delete_prefix(keys.model_dir(model_id))
    return {"deleted": model_id}
