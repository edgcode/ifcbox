"""Pydantic request/response models for the API boundary."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ifcbox.engine import RouteParams
from ifcbox.resolver import Anchor, PointAnchor, RoomAnchor, TerminalAnchor


# ── requests ──────────────────────────────────────────────────────────────────
class AnchorIn(BaseModel):
    type: Literal["point", "terminal", "room"]
    id: Optional[str] = None
    xyz: Optional[tuple[float, float, float]] = None

    def to_anchor(self) -> Anchor:
        if self.type == "point":
            if self.xyz is None:
                raise ValueError("point anchor requires xyz")
            return PointAnchor(tuple(self.xyz))
        if self.id is None:
            raise ValueError(f"{self.type} anchor requires id")
        return TerminalAnchor(self.id) if self.type == "terminal" else RoomAnchor(self.id)


class RouteParamsIn(BaseModel):
    clearance_weight: float = 5.0
    wall_penalty: float = 500.0
    bend_penalty: float = 20.0
    diameter: float = 0.1
    corridor_weight: float = 0.25
    strict_doors: bool = False
    discipline: str = "CHW"

    def to_params(self) -> RouteParams:
        return RouteParams(**self.model_dump())


class RouteRequest(BaseModel):
    source: AnchorIn
    targets: list[AnchorIn] = Field(min_length=1)
    mode: Literal["trunk", "independent"] = "trunk"
    params: RouteParamsIn = Field(default_factory=RouteParamsIn)


# ── responses ─────────────────────────────────────────────────────────────────
class StoreyOut(BaseModel):
    index: int
    name: str
    elevation: float
    height: float


class ModelOut(BaseModel):
    model_id: str
    filename: str
    storey_count: int
    status: str
    storeys: list[StoreyOut] = []


class FloorPrepStatus(BaseModel):
    model_id: str
    floor_index: int
    status: str
    stage: str = ""
    pct: int = 0


class TerminalOut(BaseModel):
    id: str
    xyz: tuple[float, float, float]   # world coords


class SpaceOut(BaseModel):
    id: str
    name: str
    centroid: tuple[float, float, float]   # world coords


class FloorDetail(BaseModel):
    model_id: str
    floor_index: int
    name: str
    status: str
    terminals: list[TerminalOut] = []
    spaces: list[SpaceOut] = []
