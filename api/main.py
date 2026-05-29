"""IFCBox backend — FastAPI app wrapping the routing engine.

Run: uvicorn api.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import require_token
from api.deps import API_PREFIX
from api.routers import floors, models, routes
from api.storage import meta


@asynccontextmanager
async def lifespan(app: FastAPI):
    meta.init()
    meta.clear_preparing()  # recover floors stuck 'preparing' from a prior process
    yield


app = FastAPI(title="IFCBox API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # single-user dev; tighten when frontend is deployed
    allow_methods=["*"],
    allow_headers=["*"],
)

_guard = [Depends(require_token)]
app.include_router(models.router, prefix=API_PREFIX, dependencies=_guard)
app.include_router(floors.router, prefix=API_PREFIX, dependencies=_guard)
app.include_router(routes.router, prefix=API_PREFIX, dependencies=_guard)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve the built frontend (api/static, populated in the Docker image) at the
# root, so prod is single-origin. Absent in local dev (frontend runs via Vite).
# Mounted last so it doesn't shadow /api or /health.
_static = Path(__file__).parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")
