"""IFCBox routing engine — the library surface the CLI and API both call.

Two layers:

  PreparedFloor   param-independent geometry for one (model, floor, resolution):
                  occupancy, clearance, zone masks, terminals, spaces. Expensive
                  to build (mesh tessellation), cached to disk via save()/load().

  route()         cheap per-request: assembles a cost grid from request params,
                  resolves anchors, runs A* (trunk or independent), returns a
                  RouteResult in world coordinates.

See plans/spec-api.md for the design and rationale.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ifcbox.pipeline.loader import (
    SiteTransform,
    StoreyInfo,
    extract_floor_geometry,
)
from ifcbox.pipeline.router import find_path
from ifcbox.pipeline.sdf import build_cost_grid, compute_clearance_field
from ifcbox.pipeline.smoother import path_length, reduce_waypoints
from ifcbox.pipeline.voxelizer import VoxelMeta, build_occupancy_grid
from ifcbox.pipeline.zoning import DOOR_ZONE_WALL_COST, build_zone_masks
from ifcbox.resolver import Anchor, anchor_id, resolve_anchor

logger = logging.getLogger(__name__)

DEFAULT_RESOLUTION = 0.1


# ── PreparedFloor (cached geometry layer) ──────────────────────────────────────

@dataclass
class PreparedFloor:
    model_id: str
    floor_index: int
    resolution: float
    storey: StoreyInfo
    meta: VoxelMeta
    site_transform: SiteTransform
    pipe_z: float

    # arrays [nx, ny]
    occupancy: np.ndarray     # bool   — True = obstacle
    wall_costs: np.ndarray    # float  — per-voxel wall crossing cost (typed)
    clearance: np.ndarray     # float  — distance_transform_edt (voxels)
    corridor: np.ndarray      # bool   — circulation-space membership
    door_zone: np.ndarray     # bool   — wall voxels above door openings
    forbidden: np.ndarray     # bool   — free voxels never routed (stairwells/shafts)

    # metadata
    terminals: dict           # {global_id: np.ndarray([x,y,z])} site-aligned
    spaces: dict              # {global_id: {"name", "centroid": np.ndarray}} site-aligned

    def save(self, dir: str | Path) -> None:
        d = Path(dir)
        d.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            d / "prepared.npz",
            occupancy=self.occupancy,
            wall_costs=self.wall_costs,
            clearance=self.clearance,
            corridor=self.corridor,
            door_zone=self.door_zone,
            forbidden=self.forbidden,
        )
        meta = {
            "model_id": self.model_id,
            "floor_index": self.floor_index,
            "resolution": self.resolution,
            "pipe_z": self.pipe_z,
            "storey": {
                "id": self.storey.id,
                "name": self.storey.name,
                "elevation": self.storey.elevation,
                "height": self.storey.height,
            },
            "meta": {
                "origin": self.meta.origin.tolist(),
                "resolution": self.meta.resolution,
                "shape": list(self.meta.shape),
            },
            "site_transform": {
                "rotation_deg": self.site_transform.rotation_deg,
                "site_matrix": self.site_transform.site_matrix.tolist(),
                "inv_matrix": self.site_transform.inv_matrix.tolist(),
            },
            "terminals": {k: np.asarray(v).tolist() for k, v in self.terminals.items()},
            "spaces": {
                k: {"name": v["name"], "centroid": np.asarray(v["centroid"]).tolist()}
                for k, v in self.spaces.items()
            },
        }
        (d / "prepared.json").write_text(json.dumps(meta))
        logger.info("Saved PreparedFloor → %s", d)

    @classmethod
    def load(cls, dir: str | Path) -> "PreparedFloor":
        d = Path(dir)
        arr = np.load(d / "prepared.npz")
        m = json.loads((d / "prepared.json").read_text())
        meta = VoxelMeta(
            origin=np.array(m["meta"]["origin"], dtype=float),
            resolution=m["meta"]["resolution"],
            shape=tuple(m["meta"]["shape"]),
        )
        st = SiteTransform(
            rotation_deg=m["site_transform"]["rotation_deg"],
            site_matrix=np.array(m["site_transform"]["site_matrix"], dtype=float),
            inv_matrix=np.array(m["site_transform"]["inv_matrix"], dtype=float),
        )
        storey = StoreyInfo(**m["storey"])
        return cls(
            model_id=m["model_id"],
            floor_index=m["floor_index"],
            resolution=m["resolution"],
            storey=storey,
            meta=meta,
            site_transform=st,
            pipe_z=m["pipe_z"],
            occupancy=arr["occupancy"],
            wall_costs=arr["wall_costs"],
            clearance=arr["clearance"],
            corridor=arr["corridor"],
            door_zone=arr["door_zone"],
            forbidden=arr["forbidden"],
            terminals={k: np.array(v, dtype=float) for k, v in m["terminals"].items()},
            spaces={
                k: {"name": v["name"], "centroid": np.array(v["centroid"], dtype=float)}
                for k, v in m["spaces"].items()
            },
        )


def prepare_floor(model, storey: StoreyInfo, floor_index: int,
                  model_id: str = "", resolution: float = DEFAULT_RESOLUTION,
                  geom=None) -> PreparedFloor:
    """Build the param-independent PreparedFloor for one storey.

    Runs loader → voxelizer → sdf → zoning (boolean masks). No request params
    enter here; cost magnitudes are applied later in route().

    Pass a pre-extracted `geom` (FloorGeometry) to avoid tessellating meshes
    twice when the caller also needs them (e.g. to export the building shell).
    """
    if geom is None:
        geom = extract_floor_geometry(model, storey)

    occupancy, wall_costs, meta = build_occupancy_grid(
        geom.meshes, geom.bounds_min, geom.bounds_max, geom.pipe_z,
        mesh_types=geom.mesh_types, resolution=resolution,
    )
    clearance = compute_clearance_field(occupancy)
    corridor, door_zone, forbidden = build_zone_masks(
        model, meta, geom.pipe_z, geom.site_transform,
    )

    return PreparedFloor(
        model_id=model_id,
        floor_index=floor_index,
        resolution=resolution,
        storey=storey,
        meta=meta,
        site_transform=geom.site_transform,
        pipe_z=geom.pipe_z,
        occupancy=occupancy,
        wall_costs=wall_costs,
        clearance=clearance,
        corridor=corridor,
        door_zone=door_zone,
        forbidden=forbidden,
        terminals=geom.terminals,
        spaces=geom.spaces,
    )


# ── route() (per-request layer) ────────────────────────────────────────────────

@dataclass
class RouteParams:
    clearance_weight: float = 5.0
    wall_penalty: float = 500.0
    bend_penalty: float = 20.0
    diameter: float = 0.1
    corridor_weight: float = 0.25   # multiplier on free corridor voxels (<1 = preferred)
    strict_doors: bool = False
    discipline: str = "generic"


@dataclass
class RouteSegment:
    target_id: str | None
    waypoints: list           # [[x,y,z], ...] world coords
    length: float
    branch_from: int | None   # index into RouteResult.branch_points, or None (trunk root)


@dataclass
class RouteResult:
    mode: str
    segments: list = field(default_factory=list)
    branch_points: list = field(default_factory=list)   # [[x,y,z], ...] world coords
    total_length: float = 0.0
    diameter: float = 0.1
    discipline: str = "generic"
    unreachable_targets: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "discipline": self.discipline,
            "diameter_m": self.diameter,
            "total_length_m": self.total_length,
            "branch_points": self.branch_points,
            "unreachable_targets": self.unreachable_targets,
            "segments": [
                {
                    "target_id": s.target_id,
                    "length_m": s.length,
                    "branch_from": s.branch_from,
                    "waypoints": s.waypoints,
                }
                for s in self.segments
            ],
        }


def build_route_mesh(result: RouteResult):
    """Merge every segment into one world-coord pipe trimesh (glTF-ready)."""
    import trimesh

    from ifcbox.pipeline.mesh import build_pipe_mesh

    parts = []
    for seg in result.segments:
        wps = [np.asarray(w, dtype=float) for w in seg.waypoints]
        if len(wps) >= 2:
            parts.append(build_pipe_mesh(wps, diameter=result.diameter))
    if not parts:
        return trimesh.Trimesh()
    return trimesh.util.concatenate(parts)


def build_routing_cost(prepared: PreparedFloor, params: RouteParams) -> np.ndarray:
    """Assemble the A* cost grid from a PreparedFloor + request params.

    Mirrors the original pipeline's cost semantics exactly:
      free      : 1 + clearance_weight / (clearance + eps)
      corridor  : free corridor voxels scaled by corridor_weight
      walls     : min(typed wall_cost, wall_penalty)   (wall_penalty is a ceiling)
      doors     : wall voxels in door zones drop to DOOR_ZONE_WALL_COST
      forbidden : free voxels set to +inf
      strict    : non-door wall voxels set to +inf
    """
    occ = prepared.occupancy
    cost = build_cost_grid(prepared.clearance, occ, wall_costs=prepared.wall_costs,
                           clearance_weight=params.clearance_weight)

    free = ~occ
    cost[prepared.corridor & free] *= params.corridor_weight
    cost[occ] = np.minimum(cost[occ], params.wall_penalty)

    wall_door = occ & prepared.door_zone
    cost[wall_door] = np.minimum(cost[wall_door], DOOR_ZONE_WALL_COST)

    cost[prepared.forbidden & free] = np.inf

    if params.strict_doors:
        cost[occ & ~prepared.door_zone] = np.inf

    return cost


def route(prepared: PreparedFloor, source: Anchor, targets: list[Anchor],
          mode: str = "trunk", params: RouteParams | None = None) -> RouteResult:
    """Route from one source anchor to N target anchors.

    mode="trunk"       : shared-main Steiner network — each target after the first
                         branches off the existing path (multi-source A* seeding).
    mode="independent" : a separate source→target path per target.
    """
    if params is None:
        params = RouteParams()
    if mode not in ("trunk", "independent"):
        raise ValueError(f"mode must be 'trunk' or 'independent', got {mode!r}")

    cost = build_routing_cost(prepared, params)
    occ = prepared.occupancy
    st = prepared.site_transform

    src_vx = resolve_anchor(source, prepared)

    result = RouteResult(mode=mode, diameter=params.diameter, discipline=params.discipline)
    network: list[tuple[int, int]] = []   # accumulated voxels (trunk mode)

    for i, tgt in enumerate(targets):
        tgt_vx = resolve_anchor(tgt, prepared)

        if mode == "independent" or i == 0:
            voxel_path = find_path(cost, occ, src_vx, tgt_vx, bend_penalty=params.bend_penalty)
            branch_from = None
        else:
            voxel_path = find_path(cost, occ, src_vx, tgt_vx,
                                   bend_penalty=params.bend_penalty, seeds=network)
            branch_from = None

        if voxel_path is None:
            result.unreachable_targets.append(anchor_id(tgt))
            continue

        if mode == "trunk":
            if i > 0:
                bp_world = st.to_world(
                    prepared.meta.voxel_to_world(*voxel_path[0], prepared.pipe_z).reshape(1, 3)
                )[0]
                branch_from = len(result.branch_points)
                result.branch_points.append([float(c) for c in bp_world])
            network.extend(voxel_path)

        site_wps = reduce_waypoints(voxel_path, prepared.meta, prepared.pipe_z)
        world_wps = [st.to_world(wp.reshape(1, 3))[0] for wp in site_wps]
        seg_len = path_length(site_wps)
        result.segments.append(RouteSegment(
            target_id=anchor_id(tgt),
            waypoints=[[float(c) for c in wp] for wp in world_wps],
            length=float(seg_len),
            branch_from=branch_from,
        ))
        result.total_length += float(seg_len)

    return result
