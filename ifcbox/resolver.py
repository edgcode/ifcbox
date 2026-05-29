"""Anchor types and resolution to voxel coordinates.

An Anchor is how a routing endpoint is specified at the request boundary:
a raw world point, a flow-terminal GlobalId, or a room (IfcSpace) GlobalId.
`resolve_anchor` maps an anchor to a voxel using a PreparedFloor's metadata.

Nearest-passable snapping is intentionally NOT done here — `router.find_path`
already nudges start/end voxels out of obstacles, so all anchor kinds get the
same treatment downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PointAnchor:
    xyz: tuple[float, float, float]   # world coords


@dataclass(frozen=True)
class TerminalAnchor:
    id: str                           # IfcFlowTerminal GlobalId


@dataclass(frozen=True)
class RoomAnchor:
    id: str                           # IfcSpace GlobalId


Anchor = PointAnchor | TerminalAnchor | RoomAnchor


class AnchorError(ValueError):
    """Raised when an anchor cannot be resolved (unknown terminal/space id)."""


def anchor_id(anchor: Anchor) -> str:
    """Stable identifier for an anchor, used in unreachable-target reporting."""
    if isinstance(anchor, PointAnchor):
        x, y, z = anchor.xyz
        return f"point:{x:.3f},{y:.3f},{z:.3f}"
    return anchor.id


def resolve_anchor(anchor: Anchor, prepared) -> tuple[int, int]:
    """Map an anchor to a voxel (vx, vy) on the prepared floor."""
    meta = prepared.meta
    if isinstance(anchor, PointAnchor):
        world = np.array(anchor.xyz, dtype=float)
        world[2] = prepared.pipe_z
        site = prepared.site_transform.to_site(world.reshape(1, 3))[0]
        return meta.world_to_voxel(site[:2])

    if isinstance(anchor, TerminalAnchor):
        if anchor.id not in prepared.terminals:
            raise AnchorError(f"terminal {anchor.id!r} not on this floor")
        return meta.world_to_voxel(prepared.terminals[anchor.id][:2])

    if isinstance(anchor, RoomAnchor):
        if anchor.id not in prepared.spaces:
            raise AnchorError(f"space {anchor.id!r} not on this floor")
        centroid = prepared.spaces[anchor.id]["centroid"]
        return meta.world_to_voxel(np.asarray(centroid)[:2])

    raise AnchorError(f"unknown anchor type: {type(anchor).__name__}")
