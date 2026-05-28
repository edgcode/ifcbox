"""Rasterize obstacle meshes into a 2D occupancy grid at 100mm resolution."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Default obstacle dilation before rasterizing (handles thin walls < resolution)
DILATION_METRES = 0.05  # 50mm


@dataclass
class VoxelMeta:
    origin: np.ndarray   # world XY coords of voxel [0, 0] corner, metres
    resolution: float    # metres per voxel
    shape: tuple[int, int]  # (nx, ny)

    def world_to_voxel(self, xy: np.ndarray) -> tuple[int, int]:
        """Convert world XY to voxel index. Clamps to grid bounds."""
        vx = int((xy[0] - self.origin[0]) / self.resolution)
        vy = int((xy[1] - self.origin[1]) / self.resolution)
        vx = np.clip(vx, 0, self.shape[0] - 1)
        vy = np.clip(vy, 0, self.shape[1] - 1)
        return int(vx), int(vy)

    def voxel_to_world(self, vx: int, vy: int, z: float) -> np.ndarray:
        """Convert voxel centre to world XYZ coordinates."""
        x = self.origin[0] + (vx + 0.5) * self.resolution
        y = self.origin[1] + (vy + 0.5) * self.resolution
        return np.array([x, y, z])


def build_occupancy_grid(
    meshes: list,
    bounds_min: np.ndarray,
    bounds_max: np.ndarray,
    pipe_z: float,
    mesh_types: list | None = None,
    resolution: float = 0.1,
    padding: float = 1.0,
    wall_penalties: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, VoxelMeta]:
    """
    Rasterize obstacle meshes into a 2D bool occupancy grid and a typed wall
    cost grid.

    Returns:
        occupancy   : bool array [nx, ny]        — True = occupied
        wall_costs  : float array [nx, ny]       — per-voxel wall crossing cost
                      (0.0 for free voxels; set from wall_penalties per mesh type)
        meta        : VoxelMeta for coord conversion
    """
    from ifcbox.pipeline.loader import (
        WALL_PENALTY_DEFAULTS, WALL_TYPE_EXTERNAL,
        WALL_TYPE_PARTITION, WALL_TYPE_PARTY,
    )

    if mesh_types is None:
        mesh_types = [WALL_TYPE_EXTERNAL] * len(meshes)
    if wall_penalties is None:
        wall_penalties = WALL_PENALTY_DEFAULTS.copy()

    # Grid origin with padding
    origin = bounds_min - padding
    extent = (bounds_max + padding) - origin
    nx = int(np.ceil(extent[0] / resolution)) + 1
    ny = int(np.ceil(extent[1] / resolution)) + 1

    meta = VoxelMeta(origin=origin, resolution=resolution, shape=(nx, ny))
    occupancy = np.zeros((nx, ny), dtype=bool)
    # wall_costs tracks the MINIMUM penalty for each wall voxel across all
    # meshes that rasterize onto it (thinner wall wins if overlap)
    wall_costs = np.zeros((nx, ny), dtype=np.float32)

    for mesh, wtype in zip(meshes, mesh_types):
        try:
            layer = np.zeros((nx, ny), dtype=bool)
            _rasterize_mesh(mesh, layer, meta, pipe_z, resolution)
            new_voxels = layer & ~occupancy
            penalty = float(wall_penalties.get(wtype, wall_penalties[WALL_TYPE_EXTERNAL]))
            # New voxels: assign penalty
            wall_costs[new_voxels] = penalty
            # Already-occupied voxels: take minimum (thinnest wall wins)
            overlap = layer & occupancy
            wall_costs[overlap] = np.minimum(wall_costs[overlap], penalty)
            occupancy |= layer
        except Exception as e:
            logger.debug("Rasterization failed for mesh: %s", e)

    # Dilate occupancy (keep wall_costs for the dilated border cells too)
    if DILATION_METRES > 0:
        dilation_voxels = max(1, int(np.ceil(DILATION_METRES / resolution)))
        dilated = _dilate(occupancy, dilation_voxels)
        # New border cells from dilation inherit the nearest wall's cost
        # (simple approach: assign the minimum non-zero surrounding cost)
        border = dilated & ~occupancy
        if border.any():
            # For dilation border, use the median non-zero wall cost as default
            nonzero = wall_costs[wall_costs > 0]
            border_penalty = float(np.median(nonzero)) if len(nonzero) else float(
                wall_penalties[WALL_TYPE_PARTITION]
            )
            wall_costs[border] = border_penalty
        occupancy = dilated

    # Mark exterior — these get the highest penalty (external wall)
    exterior_penalty = float(wall_penalties.get(WALL_TYPE_EXTERNAL,
                                                 WALL_PENALTY_DEFAULTS[WALL_TYPE_EXTERNAL]))
    occupancy, exterior_mask = _mark_exterior(occupancy, return_mask=True)
    # Exterior voxels that weren't already walls get external penalty
    new_ext = exterior_mask & (wall_costs == 0)
    wall_costs[new_ext] = exterior_penalty

    occupied = int(occupancy.sum())
    total = nx * ny
    logger.info(
        "Occupancy grid: %dx%d @ %.0fmm — %.1f%% occupied",
        nx, ny, resolution * 1000, 100 * occupied / total,
    )
    return occupancy, wall_costs, meta


def _rasterize_mesh(mesh, occupancy: np.ndarray, meta: VoxelMeta, pipe_z: float, resolution: float):
    """Rasterize a single mesh into the occupancy grid."""
    import trimesh

    vmin, vmax = mesh.bounds

    # Strategy 1: slice the mesh at pipe_z to get cross-section polygons
    z_lo = vmin[2]
    z_hi = vmax[2]

    if z_lo <= pipe_z <= z_hi:
        try:
            section = mesh.section(plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1])
            if section is not None and len(section.vertices) >= 3:
                # Use 3D section vertices directly (drop Z) — they are already in world XY
                _rasterize_section_3d(section, occupancy, meta)
                return
        except Exception:
            pass

    # Strategy 2: project mesh XY bounding box onto grid (for elements entirely
    # above or below pipe_z — e.g. walls that don't reach the routing height but
    # still block the floor plan)
    # Element doesn't span routing height — skip
    if z_lo > pipe_z or z_hi < pipe_z:
        return

    # Element spans routing height but section failed — project XY bounding box
    x0, y0 = _world_to_voxel_float(vmin[0], vmin[1], meta)
    x1, y1 = _world_to_voxel_float(vmax[0], vmax[1], meta)
    ix0 = max(0, int(np.floor(x0)))
    iy0 = max(0, int(np.floor(y0)))
    ix1 = min(meta.shape[0] - 1, int(np.ceil(x1)))
    iy1 = min(meta.shape[1] - 1, int(np.ceil(y1)))
    occupancy[ix0:ix1 + 1, iy0:iy1 + 1] = True


def _rasterize_section_3d(section, occupancy: np.ndarray, meta: VoxelMeta):
    """Fill cross-section polygons (from a 3D section path) into the occupancy grid.

    Uses section.vertices[:, :2] — already in world XY — and section.entities
    to reconstruct closed polygons.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    xy = section.vertices[:, :2]
    polygons = []
    for entity in section.entities:
        try:
            pts = xy[entity.points]
            if len(pts) >= 3:
                poly = Polygon(pts)
                if poly.is_valid and poly.area > 1e-6:
                    polygons.append(poly)
        except Exception:
            continue

    if not polygons:
        # Fallback: convex hull of all section vertices
        from shapely.geometry import MultiPoint
        hull = MultiPoint(xy).convex_hull
        if hull.area > 1e-6:
            polygons = [hull]

    if not polygons:
        return

    combined = unary_union(polygons)
    _fill_shapely_polygon(combined, occupancy, meta)


def _fill_shapely_polygon(geom, occupancy: np.ndarray, meta: VoxelMeta):
    """Rasterize a shapely geometry into the occupancy grid."""
    from shapely.geometry import MultiPolygon, Polygon

    if geom.is_empty:
        return
    if isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            _fill_shapely_polygon(poly, occupancy, meta)
        return
    if not isinstance(geom, Polygon):
        return

    bounds = geom.bounds  # (minx, miny, maxx, maxy)
    ix0, iy0 = meta.world_to_voxel(np.array([bounds[0], bounds[1]]))
    ix1, iy1 = meta.world_to_voxel(np.array([bounds[2], bounds[3]]))

    for ix in range(ix0, min(ix1 + 1, meta.shape[0])):
        for iy in range(iy0, min(iy1 + 1, meta.shape[1])):
            # Test voxel centre
            cx = meta.origin[0] + (ix + 0.5) * meta.resolution
            cy = meta.origin[1] + (iy + 0.5) * meta.resolution
            from shapely.geometry import Point
            if geom.contains(Point(cx, cy)):
                occupancy[ix, iy] = True


def _world_to_voxel_float(x: float, y: float, meta: VoxelMeta) -> tuple[float, float]:
    vx = (x - meta.origin[0]) / meta.resolution
    vy = (y - meta.origin[1]) / meta.resolution
    return vx, vy


def _mark_exterior(
    occupancy: np.ndarray,
    return_mask: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Flood-fill from grid boundary to find exterior space, mark it occupied."""
    from collections import deque

    nx, ny = occupancy.shape
    exterior = np.zeros_like(occupancy)
    queue = deque()

    for x in range(nx):
        for y in [0, ny - 1]:
            if not occupancy[x, y] and not exterior[x, y]:
                exterior[x, y] = True
                queue.append((x, y))
    for y in range(ny):
        for x in [0, nx - 1]:
            if not occupancy[x, y] and not exterior[x, y]:
                exterior[x, y] = True
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nx_, ny_ = x + dx, y + dy
            if 0 <= nx_ < nx and 0 <= ny_ < ny and not occupancy[nx_, ny_] and not exterior[nx_, ny_]:
                exterior[nx_, ny_] = True
                queue.append((nx_, ny_))

    result = occupancy.copy()
    result[exterior] = True
    logger.debug("Exterior cells marked: %d", int(exterior.sum()))
    if return_mask:
        return result, exterior
    return result


def _dilate(grid: np.ndarray, radius: int) -> np.ndarray:
    """Binary dilation to expand obstacle footprints."""
    from scipy.ndimage import binary_dilation
    struct = np.ones((2 * radius + 1, 2 * radius + 1), dtype=bool)
    return binary_dilation(grid, structure=struct)


def debug_png(occupancy: np.ndarray, path: str, waypoints: list | None = None, meta: VoxelMeta | None = None):
    """Save occupancy grid as a grayscale PNG for debugging. Optionally overlay waypoints."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 12))
    ax.imshow(occupancy.T, origin="lower", cmap="binary", interpolation="nearest")

    if waypoints and meta is not None:
        xs = [(meta.world_to_voxel(wp[:2])[0]) for wp in waypoints]
        ys = [(meta.world_to_voxel(wp[:2])[1]) for wp in waypoints]
        ax.plot(xs, ys, "r-o", linewidth=1.5, markersize=4, label="route")
        ax.legend()

    ax.set_title(f"Occupancy grid {occupancy.shape[0]}×{occupancy.shape[1]}")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("Saved debug PNG: %s", path)
