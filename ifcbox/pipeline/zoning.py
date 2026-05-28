"""
Zone-aware cost modifiers.

Produces two overlays applied to the A* cost grid:
  1. Corridor preference  — voxels inside circulation spaces are cheaper to route through
  2. Door crossing zones  — wall voxels above doors are cheaper to punch through
"""

from __future__ import annotations

import logging
import re

import numpy as np

from .voxelizer import VoxelMeta, _fill_shapely_polygon, _rasterize_section_3d

logger = logging.getLogger(__name__)

# ── Corridor identification ───────────────────────────────────────────────────

# Space name prefixes / substrings that indicate circulation spaces (DE + EN)
CIRCULATION_PATTERNS = re.compile(
    r"^(flur|korridor|gang|treppenraum|treppenhaus|foyer|diele|vorraum|"
    r"erschlie|hausflur|corridor|circulation|hall|lobby|passage|stair|lift|"
    r"aufzug|elevat)",
    re.IGNORECASE,
)

# Spaces that pipes must NOT pass through (communal/shared, structurally critical)
FORBIDDEN_PATTERNS = re.compile(
    r"^(treppenraum|treppenhaus|stairwell|stair|aufzug|lift|elevator|"
    r"schacht|shaft|riser)",
    re.IGNORECASE,
)

# Preferred corridor patterns — same as CIRCULATION but excluding forbidden ones
PREFERRED_CORRIDOR_PATTERNS = re.compile(
    r"^(flur|korridor|gang|foyer|diele|vorraum|erschlie|hausflur|"
    r"corridor|circulation|hall|lobby|passage)",
    re.IGNORECASE,
)

# Cost multiplier applied to free voxels inside circulation spaces
CORRIDOR_COST_MULTIPLIER = 0.25   # 4× cheaper than open room space

# ── Door zone identification ──────────────────────────────────────────────────

# Reduced wall penalty for crossing at a door location (vs default 500)
DOOR_ZONE_WALL_COST = 30.0        # ~6% of normal wall penalty

# Half-width of the door crossing zone (each side of door centreline), metres
DOOR_ZONE_HALF_WIDTH = 0.6        # covers a 1.2m swath ≈ standard door width


def build_zone_modifiers(
    model,
    meta: VoxelMeta,
    pipe_z: float,
    site_xform,
    occupancy: np.ndarray,
    wall_penalty: float = 500.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build zone modifier arrays:

    corridor_mask  : float [nx, ny]  — cost multiplier for free voxels (< 1.0 = preferred)
    door_wall_cost : float [nx, ny]  — replacement wall cost at door crossing zones
    forbidden_mask : bool  [nx, ny]  — free voxels that must not be routed through
                                       (Treppenraum, lift shafts, etc.)

    Returns (corridor_mask, door_wall_cost, forbidden_mask).
    """
    nx, ny = meta.shape
    corridor_mask = np.ones((nx, ny), dtype=np.float32)
    door_wall_cost = np.full((nx, ny), wall_penalty, dtype=np.float32)
    forbidden_mask = np.zeros((nx, ny), dtype=bool)

    _apply_corridor_preference(model, meta, pipe_z, site_xform, corridor_mask)
    _apply_forbidden_zones(model, meta, pipe_z, site_xform, forbidden_mask)
    _apply_door_zones(model, meta, pipe_z, site_xform, occupancy, door_wall_cost)

    return corridor_mask, door_wall_cost, forbidden_mask


def apply_zone_modifiers(
    cost_grid: np.ndarray,
    occupancy: np.ndarray,
    corridor_mask: np.ndarray,
    door_wall_cost: np.ndarray,
) -> np.ndarray:
    """
    Apply corridor and door-zone modifiers to an existing cost grid.

    Free voxels in corridors are scaled down by corridor_mask.
    Wall voxels at door locations get door_wall_cost instead of wall_penalty.
    """
    modified = cost_grid.copy()

    # Scale free-space cost in corridors
    free = ~occupancy
    modified[free] *= corridor_mask[free]

    # Override wall cost at door zones (only where door_wall_cost < current cost)
    modified[occupancy] = np.minimum(modified[occupancy], door_wall_cost[occupancy])

    return modified


# ── Internal helpers ──────────────────────────────────────────────────────────

def _apply_forbidden_zones(model, meta, pipe_z, site_xform, forbidden_mask):
    """Mark free voxels inside communal/forbidden spaces as impassable."""
    import ifcopenshell.geom
    import trimesh

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    found = 0
    for space in model.by_type("IfcSpace"):
        name = (space.Name or "").strip()
        if not FORBIDDEN_PATTERNS.match(name):
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            faces = np.array(shape.geometry.faces).reshape(-1, 3)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            mesh = site_xform.transform_mesh(mesh)
            zn, zx = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
            if zx < pipe_z - 0.5 or zn > pipe_z + 0.5:
                continue
            section = mesh.section(plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1])
            if section is not None and len(section.vertices) >= 3:
                _rasterize_section_3d(section, forbidden_mask, meta)
                found += 1
        except Exception as e:
            logger.debug("Forbidden space %r geometry failed: %s", name, e)

    logger.info("Marked %d forbidden zones (Treppenraum etc.)", found)


def _apply_corridor_preference(model, meta, pipe_z, site_xform, corridor_mask):
    """Mark voxels inside preferred circulation spaces with corridor cost multiplier."""
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import trimesh

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    found = 0
    for space in model.by_type("IfcSpace"):
        name = (space.Name or "").strip()
        if not PREFERRED_CORRIDOR_PATTERNS.match(name):
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            faces = np.array(shape.geometry.faces).reshape(-1, 3)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            # Transform to site-aligned coords
            mesh = site_xform.transform_mesh(mesh)

            z_lo, z_hi = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
            if z_hi < pipe_z - 0.5 or z_lo > pipe_z + 0.5:
                continue

            # Slice at pipe_z and fill
            section = mesh.section(plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1])
            if section is not None and len(section.vertices) >= 3:
                mask = np.zeros(meta.shape, dtype=bool)
                _rasterize_section_3d(section, mask, meta)
                corridor_mask[mask] = CORRIDOR_COST_MULTIPLIER
                found += 1
        except Exception as e:
            logger.debug("Corridor space %r geometry failed: %s", name, e)

    logger.info("Applied corridor preference to %d circulation spaces", found)


def _apply_door_zones(model, meta, pipe_z, site_xform, occupancy, door_wall_cost):
    """Mark wall voxels above door openings with reduced crossing cost."""
    import ifcopenshell.util.placement

    found = 0
    for door in model.by_type("IfcDoor"):
        try:
            h = getattr(door, "OverallHeight", None)
            w = getattr(door, "OverallWidth", None)
            if h is None or w is None:
                continue
            # Only mark doors where pipe_z is above the door top
            # (the zone between door lintel and slab — non-structural transom)
            door_top = float(h)  # height is relative to floor
            floor_elev = float(
                ifcopenshell.util.placement.get_local_placement(
                    door.ObjectPlacement
                )[2, 3]
            )
            abs_door_top = floor_elev + door_top
            if pipe_z <= abs_door_top:
                continue  # pipe routes below door top — opening is free anyway

            # Door position in world coords → site-aligned
            mat = ifcopenshell.util.placement.get_local_placement(door.ObjectPlacement)
            world_pos = mat[:3, 3]
            site_pos = site_xform.to_site(world_pos.reshape(1, 3))[0]

            # Door X-axis = along door width (wall face direction) in world coords
            world_x = mat[:3, 0]
            # Transform the direction (rotation only, no translation)
            rot3 = site_xform.site_matrix[:3, :3]
            site_x = rot3 @ world_x
            site_x = site_x[:2] / (np.linalg.norm(site_x[:2]) + 1e-9)

            # Wall-normal = perpendicular to door width axis in 2D
            wall_normal = np.array([-site_x[1], site_x[0]])

            # Mark a rectangular zone:  ±half_width along door face, ±2 voxels through wall
            hw = float(w) / 2.0
            door_centre = site_pos[:2]

            _mark_door_zone(
                door_wall_cost, meta, door_centre, site_x, wall_normal, hw
            )
            found += 1
        except Exception as e:
            logger.debug("Door #%d zone failed: %s", door.id(), e)

    logger.info("Applied door crossing zones to %d doors", found)


def _mark_door_zone(
    door_wall_cost: np.ndarray,
    meta: VoxelMeta,
    centre: np.ndarray,
    along_wall: np.ndarray,   # unit vec along door face (X of door)
    thru_wall: np.ndarray,    # unit vec through wall (Y of door opening)
    half_width: float,
    thru_depth: float = 0.3,  # metres through the wall to mark
):
    """Mark a rectangular slot in door_wall_cost with DOOR_ZONE_WALL_COST."""
    r = meta.resolution

    # Sample points along the door width
    steps_along = max(1, int(np.ceil(half_width / r)))
    steps_thru = max(1, int(np.ceil(thru_depth / r)))

    for i in range(-steps_along, steps_along + 1):
        for j in range(-steps_thru, steps_thru + 1):
            pt = centre + (i * r) * along_wall + (j * r) * thru_wall
            vx, vy = meta.world_to_voxel(pt)
            nx, ny = door_wall_cost.shape
            if 0 <= vx < nx and 0 <= vy < ny:
                door_wall_cost[vx, vy] = min(door_wall_cost[vx, vy], DOOR_ZONE_WALL_COST)
