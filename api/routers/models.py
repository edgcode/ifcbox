"""Model upload and lifecycle endpoints."""

from __future__ import annotations

import json
import shutil
import uuid

from fastapi import APIRouter, HTTPException, UploadFile

from ifcbox.pipeline.loader import _length_unit_scale, list_storeys, load_model
from api import cache
from api.schemas import ModelOut, StoreyOut
from api.store import db, files

router = APIRouter(tags=["models"])


def _storeys_from_meta(model_id: str) -> list[StoreyOut]:
    meta = json.loads(files.model_meta(model_id).read_text())
    return [StoreyOut(**s) for s in meta["storeys"]]


@router.post("/models", response_model=ModelOut)
async def upload_model(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".ifc"):
        raise HTTPException(422, "expected a .ifc file")

    model_id = uuid.uuid4().hex[:12]
    files.model_dir(model_id).mkdir(parents=True, exist_ok=True)
    ifc_path = files.model_ifc(model_id)
    with ifc_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        model = load_model(ifc_path)
        storeys = list_storeys(model)
        unit_scale = _length_unit_scale(model)
    except Exception as e:
        shutil.rmtree(files.model_dir(model_id), ignore_errors=True)
        raise HTTPException(422, f"could not parse IFC: {e}")

    storeys_out = [
        StoreyOut(index=i, name=s.name, elevation=s.elevation, height=s.height)
        for i, s in enumerate(storeys)
    ]
    files.model_meta(model_id).write_text(json.dumps({
        "filename": file.filename,
        "unit_scale": unit_scale,
        "storeys": [s.model_dump() for s in storeys_out],
    }))
    db.insert_model(model_id, file.filename, len(storeys), unit_scale)

    return ModelOut(model_id=model_id, filename=file.filename,
                    storey_count=len(storeys), status="uploaded", storeys=storeys_out)


@router.get("/models")
async def list_models():
    return [
        {"model_id": r["id"], "filename": r["filename"],
         "storey_count": r["storey_count"], "status": r["status"],
         "uploaded_at": r["uploaded_at"]}
        for r in db.list_models()
    ]


@router.get("/models/{model_id}", response_model=ModelOut)
async def get_model(model_id: str):
    row = db.get_model(model_id)
    if row is None:
        raise HTTPException(404, "model not found")
    return ModelOut(
        model_id=row["id"], filename=row["filename"],
        storey_count=row["storey_count"], status=row["status"],
        storeys=_storeys_from_meta(model_id),
    )


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    if db.get_model(model_id) is None:
        raise HTTPException(404, "model not found")
    db.delete_model(model_id)
    cache.evict_model(model_id)
    shutil.rmtree(files.model_dir(model_id), ignore_errors=True)
    return {"deleted": model_id}
