"""Pipe mesh generation — extrude a circular cross-section along waypoint segments."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

PIPE_SIDES = 12  # polygon approximation for circular cross-section


def build_pipe_mesh(
    waypoints: list[np.ndarray],
    diameter: float = 0.1,
) -> "trimesh.Trimesh":
    """
    Build a 3D pipe mesh by extruding a circular cross-section along the waypoint polyline.

    Each straight segment gets a cylinder. Joints between segments are handled by
    sharing the cross-section at the bend point (sufficient for draft visualisation).

    Returns a single merged trimesh.Trimesh.
    """
    import trimesh
    import trimesh.creation

    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints to build a pipe mesh")

    radius = diameter / 2.0
    segments = []

    for i in range(len(waypoints) - 1):
        a = waypoints[i]
        b = waypoints[i + 1]
        seg = _cylinder_segment(a, b, radius)
        if seg is not None:
            segments.append(seg)

    # End caps
    segments.append(_sphere_cap(waypoints[0], radius))
    segments.append(_sphere_cap(waypoints[-1], radius))

    if not segments:
        raise ValueError("No valid pipe segments generated")

    pipe = trimesh.util.concatenate(segments)
    logger.info(
        "Pipe mesh: %d vertices, %d faces, length=%.2fm",
        len(pipe.vertices),
        len(pipe.faces),
        _polyline_length(waypoints),
    )
    return pipe


def _cylinder_segment(a: np.ndarray, b: np.ndarray, radius: float):
    """Create a cylinder trimesh between two 3D points."""
    import trimesh
    import trimesh.creation

    vec = b - a
    length = float(np.linalg.norm(vec))
    if length < 1e-6:
        return None

    # trimesh.creation.cylinder creates along Z axis, then we transform
    cyl = trimesh.creation.cylinder(radius=radius, height=length, sections=PIPE_SIDES)

    # Build transform: translate to midpoint, rotate Z→direction
    mid = (a + b) / 2.0
    direction = vec / length

    transform = _rotation_matrix_z_to(direction)
    transform[:3, 3] = mid

    cyl.apply_transform(transform)
    return cyl


def _sphere_cap(centre: np.ndarray, radius: float):
    """Icosphere cap at a pipe endpoint."""
    import trimesh
    import trimesh.creation

    sphere = trimesh.creation.icosphere(subdivisions=1, radius=radius)
    sphere.apply_translation(centre)
    return sphere


def _rotation_matrix_z_to(direction: np.ndarray) -> np.ndarray:
    """4×4 rotation matrix that maps Z-axis to the given direction vector."""
    z = np.array([0.0, 0.0, 1.0])
    d = direction / np.linalg.norm(direction)

    dot = float(np.dot(z, d))

    # Parallel case
    if abs(dot - 1.0) < 1e-8:
        return np.eye(4)
    if abs(dot + 1.0) < 1e-8:
        # Antiparallel — rotate 180° around X
        m = np.eye(4)
        m[1, 1] = -1
        m[2, 2] = -1
        return m

    axis = np.cross(z, d)
    axis = axis / np.linalg.norm(axis)
    angle = np.arccos(np.clip(dot, -1.0, 1.0))

    # Rodrigues rotation formula → 3×3 rotation matrix
    c = np.cos(angle)
    s = np.sin(angle)
    t = 1.0 - c
    x, y, zv = axis

    rot = np.array([
        [t * x * x + c,     t * x * y - s * zv, t * x * zv + s * y],
        [t * x * y + s * zv, t * y * y + c,     t * y * zv - s * x],
        [t * x * zv - s * y, t * y * zv + s * x, t * zv * zv + c  ],
    ])

    m = np.eye(4)
    m[:3, :3] = rot
    return m


def _polyline_length(waypoints: list[np.ndarray]) -> float:
    return sum(
        float(np.linalg.norm(waypoints[i + 1] - waypoints[i]))
        for i in range(len(waypoints) - 1)
    )
