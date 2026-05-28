"""Waypoint reduction — collapse a voxel path to minimal 3D bend points."""

from __future__ import annotations

import logging

import numpy as np

from .voxelizer import VoxelMeta

logger = logging.getLogger(__name__)


def reduce_waypoints(
    voxel_path: list[tuple[int, int]],
    meta: VoxelMeta,
    pipe_z: float,
) -> list[np.ndarray]:
    """
    Convert a dense voxel path to a minimal list of 3D world-coordinate waypoints.

    Collinear consecutive voxels are collapsed: only direction-change points are kept.
    The result is a polyline of 3D points suitable for pipe mesh extrusion.

    Returns at least 2 points (start and end).
    """
    if len(voxel_path) == 0:
        return []
    if len(voxel_path) == 1:
        vx, vy = voxel_path[0]
        return [meta.voxel_to_world(vx, vy, pipe_z)]

    waypoints = [voxel_path[0]]

    for i in range(1, len(voxel_path) - 1):
        prev = voxel_path[i - 1]
        curr = voxel_path[i]
        nxt = voxel_path[i + 1]

        dir_in = (curr[0] - prev[0], curr[1] - prev[1])
        dir_out = (nxt[0] - curr[0], nxt[1] - curr[1])

        if dir_in != dir_out:
            waypoints.append(curr)

    waypoints.append(voxel_path[-1])

    world_waypoints = [
        meta.voxel_to_world(vx, vy, pipe_z)
        for vx, vy in waypoints
    ]

    logger.info(
        "Reduced %d voxels → %d waypoints (%.0f%% reduction)",
        len(voxel_path),
        len(world_waypoints),
        100 * (1 - len(world_waypoints) / len(voxel_path)),
    )
    return world_waypoints


def path_length(waypoints: list[np.ndarray]) -> float:
    """Total Euclidean length of the waypoint polyline in metres."""
    if len(waypoints) < 2:
        return 0.0
    return sum(
        float(np.linalg.norm(waypoints[i + 1] - waypoints[i]))
        for i in range(len(waypoints) - 1)
    )
