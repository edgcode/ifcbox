"""
Zone geometry masks (param-independent).

Produces boolean masks that the engine's route() turns into cost modifiers:
  1. corridor   — free voxels inside circulation spaces (cheaper to route through)
  2. door_zone  — wall voxels above doors (cheaper to punch through)
  3. forbidden  — free voxels inside stairwells / shafts (never routed)

Cost magnitudes (corridor_weight, door-crossing cost, wall_penalty) are applied
downstream from request params, not here — these masks depend on geometry only.
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

# Default cost multiplier applied to free voxels inside circulation spaces.
# Exposed at route time as RouteParams.corridor_weight.
DEFAULT_CORRIDOR_WEIGHT = 0.25    # 4× cheaper than open room space

# Reduced wall crossing cost at a door location (vs default wall_penalty ~500)
DOOR_ZONE_WALL_COST = 30.0        # ~6% of normal wall penalty


def build_zone_masks(
    model,
    meta: VoxelMeta,
    pipe_z: float,
    site_xform,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build param-independent boolean zone masks for a floor.

    corridor  : bool [nx, ny]  — voxels inside preferred circulation spaces
    door_zone : bool [nx, ny]  — wall voxels above door openings (cheap to cross)
    forbidden : bool [nx, ny]  — free voxels that must not be routed (stairwells, shafts)

    Returns (corridor, door_zone, forbidden). Cost magnitudes are applied by the
    engine's route() from request params.
    """
    nx, ny = meta.shape
    corridor = np.zeros((nx, ny), dtype=bool)
    door_zone = np.zeros((nx, ny), dtype=bool)
    forbidden = np.zeros((nx, ny), dtype=bool)

    _apply_corridor_preference(model, meta, pipe_z, site_xform, corridor)
    _apply_forbidden_zones(model, meta, pipe_z, site_xform, forbidden)
    _apply_door_zones(model, meta, pipe_z, site_xform, door_zone)

    return corridor, door_zone, forbidden


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


def _apply_corridor_preference(model, meta, pipe_z, site_xform, corridor):
    """Mark voxels inside preferred circulation spaces as corridor (True)."""
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
                _rasterize_section_3d(section, corridor, meta)
                found += 1
        except Exception as e:
            logger.debug("Corridor space %r geometry failed: %s", name, e)

    logger.info("Applied corridor preference to %d circulation spaces", found)


def _apply_door_zones(model, meta, pipe_z, site_xform, door_zone):
    """Mark wall voxels above door openings as door crossing zones (True)."""
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
                door_zone, meta, door_centre, site_x, wall_normal, hw
            )
            found += 1
        except Exception as e:
            logger.debug("Door #%d zone failed: %s", door.id(), e)

    logger.info("Applied door crossing zones to %d doors", found)


def _mark_door_zone(
    door_zone: np.ndarray,
    meta: VoxelMeta,
    centre: np.ndarray,
    along_wall: np.ndarray,   # unit vec along door face (X of door)
    thru_wall: np.ndarray,    # unit vec through wall (Y of door opening)
    half_width: float,
    thru_depth: float = 0.3,  # metres through the wall to mark
):
    """Mark a rectangular slot in the boolean door_zone mask."""
    r = meta.resolution

    # Sample points along the door width
    steps_along = max(1, int(np.ceil(half_width / r)))
    steps_thru = max(1, int(np.ceil(thru_depth / r)))

    nx, ny = door_zone.shape
    for i in range(-steps_along, steps_along + 1):
        for j in range(-steps_thru, steps_thru + 1):
            pt = centre + (i * r) * along_wall + (j * r) * thru_wall
            vx, vy = meta.world_to_voxel(pt)
            if 0 <= vx < nx and 0 <= vy < ny:
                door_zone[vx, vy] = True
