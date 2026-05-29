"""IFC loading, storey extraction, obstacle mesh extraction, flow terminal extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# IFC types treated as routing obstacles
OBSTACLE_TYPES = {
    "IfcWall",
    "IfcWallStandardCase",
    "IfcColumn",
    # "IfcBeam",
    "IfcCurtainWall",
    "IfcStair",
    "IfcStairFlight",
    "IfcRamp",
    "IfcRampFlight",
}

# Routing elevation above storey slab
PIPE_Z_OFFSET = 2.5  # metres above storey elevation


@dataclass
class SiteTransform:
    """Encapsulates the site-alignment transform derived from IfcSite placement.

    Applying `to_site` to world-coord geometry un-rotates and un-translates
    the building so walls align with the X/Y axes — much better voxel alignment.
    Applying `to_world` converts analysis results back to world coords for export.
    """
    rotation_deg: float          # building rotation from world axes, in degrees
    site_matrix: np.ndarray      # 4×4 site placement matrix (world → site)
    inv_matrix: np.ndarray       # inverse: site coords → world coords

    def to_site(self, points: np.ndarray) -> np.ndarray:
        """Transform Nx3 world coords → site-aligned coords."""
        ones = np.ones((len(points), 1))
        h = np.hstack([points, ones])
        return (self.site_matrix @ h.T).T[:, :3]

    def to_world(self, points: np.ndarray) -> np.ndarray:
        """Transform Nx3 site-aligned coords → world coords."""
        ones = np.ones((len(points), 1))
        h = np.hstack([points, ones])
        return (self.inv_matrix @ h.T).T[:, :3]

    def transform_mesh(self, mesh) -> "trimesh.Trimesh":
        """Return a copy of a world-coord mesh transformed into site coords."""
        m = mesh.copy()
        m.vertices = self.to_site(m.vertices)
        return m

    def world_mesh(self, mesh) -> "trimesh.Trimesh":
        """Return a copy of a site-aligned mesh transformed back into world coords."""
        m = mesh.copy()
        m.vertices = self.to_world(m.vertices)
        return m


def get_site_transform(model) -> SiteTransform:
    """Extract the site alignment transform from IfcSite placement.

    The IfcSite placement matrix encodes how the project's world coordinate
    system is rotated/translated relative to the building's natural axes.
    Inverting it aligns the building with X/Y for voxelisation.

    Falls back to identity if no site placement is found.
    """
    import ifcopenshell.util.placement

    sites = model.by_type("IfcSite")
    if sites and sites[0].ObjectPlacement:
        mat = ifcopenshell.util.placement.get_local_placement(sites[0].ObjectPlacement)
    else:
        mat = np.eye(4)

    rotation_deg = float(np.degrees(np.arctan2(mat[1, 0], mat[0, 0])))
    inv = np.linalg.inv(mat)

    logger.info(
        "Site transform: rotation=%.2f°, origin=[%.3f, %.3f]",
        rotation_deg, mat[0, 3], mat[1, 3],
    )
    return SiteTransform(
        rotation_deg=rotation_deg,
        site_matrix=inv,   # world → site-aligned (apply this to geometry)
        inv_matrix=mat,    # site-aligned → world (apply to results for export)
    )


@dataclass
class StoreyInfo:
    id: int           # IfcBuildingStorey step id
    name: str
    elevation: float  # metres, in IFC world coords
    height: float     # metres (0 if unknown)


# Wall type classifications — used for per-type routing penalties
WALL_TYPE_PARTITION = "partition"   # lightweight internal wall  (≤175mm)
WALL_TYPE_PARTY     = "party"       # heavy / party wall         (175–350mm)
WALL_TYPE_EXTERNAL  = "external"    # external / structural wall (>350mm)

# Default wall penalty per type (multipliers over base; overridable at runtime)
WALL_PENALTY_DEFAULTS = {
    WALL_TYPE_PARTITION: 100.0,
    WALL_TYPE_PARTY:     600.0,
    WALL_TYPE_EXTERNAL: 1500.0,
}


def classify_wall_thickness(mesh) -> str:
    """Classify a wall mesh by its minimum XY extent (proxy for thickness)."""
    dx = float(mesh.bounds[1][0] - mesh.bounds[0][0])
    dy = float(mesh.bounds[1][1] - mesh.bounds[0][1])
    thickness = min(dx, dy)
    if thickness <= 0.175:
        return WALL_TYPE_PARTITION
    if thickness <= 0.350:
        return WALL_TYPE_PARTY
    return WALL_TYPE_EXTERNAL


@dataclass
class FloorGeometry:
    storey: StoreyInfo
    meshes: list            # list[trimesh.Trimesh] — in site-aligned coords
    mesh_types: list        # list[str] — wall type per mesh (WALL_TYPE_*)
    elements: list          # list[dict] per mesh: id, ifc_type, thickness_m, wall_type, wall_type_name, fire_rating
    terminals: dict         # {ifc_id: np.ndarray([x, y, z])} — in site-aligned coords
    spaces: dict            # {global_id: {"name": str, "centroid": [x,y,z]}} — site-aligned
    bounds_min: np.ndarray  # [x, y] metres, site-aligned
    bounds_max: np.ndarray  # [x, y] metres, site-aligned
    pipe_z: float           # absolute Z for pipe routing (Z is unchanged by 2D rotation)
    site_transform: SiteTransform  # for converting results back to world coords


def load_model(ifc_path: str | Path):
    """Load an IFC file and return the ifcopenshell model."""
    import ifcopenshell
    path = str(ifc_path)
    logger.info("Loading IFC: %s", path)
    model = ifcopenshell.open(path)
    logger.info("Loaded — schema: %s", model.schema)
    return model


def _length_unit_scale(model) -> float:
    """Return the factor to convert project length units → metres (e.g. 0.001 for mm)."""
    _PREFIX = {
        "EXA": 1e18, "PETA": 1e15, "TERA": 1e12, "GIGA": 1e9,
        "MEGA": 1e6,  "KILO": 1e3,  "HECTO": 1e2, "DECA": 1e1,
        "DECI": 1e-1, "CENTI": 1e-2, "MILLI": 1e-3,
        "MICRO": 1e-6, "NANO": 1e-9, "PICO": 1e-12,
    }
    try:
        for assignment in model.by_type("IfcUnitAssignment"):
            for unit in assignment.Units:
                if unit.is_a("IfcSIUnit") and unit.UnitType == "LENGTHUNIT":
                    return _PREFIX.get(getattr(unit, "Prefix", None), 1.0)
    except Exception:
        pass
    return 1.0


def list_storeys(model) -> list[StoreyInfo]:
    """Return all IfcBuildingStorey elements sorted by elevation."""
    unit_scale = _length_unit_scale(model)
    if unit_scale != 1.0:
        logger.info("Length unit scale: %.6f (project units → metres)", unit_scale)
    storeys = []
    for s in model.by_type("IfcBuildingStorey"):
        elevation = _get_elevation(s, unit_scale)
        storeys.append(StoreyInfo(
            id=s.id(),
            name=s.Name or f"Storey {s.id()}",
            elevation=elevation,
            height=0.0,
        ))
    storeys.sort(key=lambda s: s.elevation)

    # Infer storey heights from successive elevations
    for i, s in enumerate(storeys[:-1]):
        s.height = storeys[i + 1].elevation - s.elevation
    if storeys:
        storeys[-1].height = 4.0  # fallback for top storey

    return storeys


def extract_floor_geometry(model, storey: StoreyInfo) -> FloorGeometry:
    """Extract obstacle meshes and flow terminal positions for a storey.

    All geometry is returned in site-aligned coordinates (building axes = X/Y)
    for cleaner voxel alignment. Use floor_geom.site_transform.to_world() to
    convert routing results back to IFC world coordinates for export.

    Obstacles are collected from ALL elements whose mesh Z range overlaps the
    routing elevation, regardless of which IFC storey they are assigned to.
    """
    import ifcopenshell.geom
    import trimesh

    site_xform = get_site_transform(model)

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    pipe_z = storey.elevation + PIPE_Z_OFFSET
    z_lo_accept = pipe_z - 0.5
    z_hi_accept = pipe_z + 0.5

    from ifcbox.wall_attrs import wall_fire_rating, wall_type_name

    meshes = []
    mesh_types = []
    elements = []
    failed = 0

    # Wall types get thickness-based classification; non-wall obstacles are external
    wall_ifc_types = {
        "IfcWall", "IfcWallStandardCase", "IfcCurtainWall",
    }

    for ifc_type in OBSTACLE_TYPES:
        for element in model.by_type(ifc_type):
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
                mesh = _shape_to_trimesh(shape)
                if mesh is None or len(mesh.vertices) == 0:
                    continue
                z_min = float(mesh.bounds[0][2])
                z_max = float(mesh.bounds[1][2])
                if z_max < z_lo_accept or z_min > z_hi_accept:
                    continue
                site_mesh = site_xform.transform_mesh(mesh)
                meshes.append(site_mesh)
                is_wall = ifc_type in wall_ifc_types
                wtype = classify_wall_thickness(site_mesh) if is_wall else WALL_TYPE_EXTERNAL
                mesh_types.append(wtype)
                dx = float(site_mesh.bounds[1][0] - site_mesh.bounds[0][0])
                dy = float(site_mesh.bounds[1][1] - site_mesh.bounds[0][1])
                elements.append({
                    "id": element.GlobalId,
                    "ifc_type": ifc_type,
                    "thickness_m": round(min(dx, dy), 4),
                    "wall_type": wtype,
                    "wall_type_name": wall_type_name(element) if is_wall else "—",
                    "fire_rating": wall_fire_rating(element) if is_wall else "—",
                })
            except Exception as e:
                failed += 1
                logger.debug("Mesh extraction failed for %s #%d: %s", ifc_type, element.id(), e)

    if failed:
        logger.warning("Skipped %d elements with geometry errors", failed)

    # Log type breakdown
    from collections import Counter
    type_counts = Counter(mesh_types)
    logger.info(
        "Extracted %d obstacle meshes for storey '%s' — partition:%d party:%d external:%d",
        len(meshes), storey.name,
        type_counts[WALL_TYPE_PARTITION],
        type_counts[WALL_TYPE_PARTY],
        type_counts[WALL_TYPE_EXTERNAL],
    )

    terminals = _extract_terminals(model, storey, site_xform)
    logger.info("Found %d flow terminals on storey '%s'", len(terminals), storey.name)

    spaces = extract_floor_spaces(model, pipe_z, site_xform)
    logger.info("Found %d spaces on storey '%s'", len(spaces), storey.name)

    bounds_min, bounds_max = _compute_xy_bounds(meshes)

    return FloorGeometry(
        storey=storey,
        meshes=meshes,
        mesh_types=mesh_types,
        elements=elements,
        terminals=terminals,
        spaces=spaces,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        pipe_z=storey.elevation + PIPE_Z_OFFSET,
        site_transform=site_xform,
    )


def _extract_terminals(model, storey: StoreyInfo, site_xform: SiteTransform) -> dict:
    """Return {ifc_global_id: np.array([x, y, z])} in site-aligned coords."""
    import ifcopenshell.util.placement

    terminals = {}
    for element in model.by_type("IfcFlowTerminal"):
        if not _element_on_storey(element, storey, model):
            continue
        try:
            matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
            world_pos = np.array(matrix[:3, 3], dtype=float)
            site_pos = site_xform.to_site(world_pos.reshape(1, 3))[0]
            terminals[element.GlobalId] = site_pos
        except Exception as e:
            logger.debug("Terminal placement failed for %s: %s", element.GlobalId, e)

    return terminals


def extract_floor_spaces(model, pipe_z: float, site_xform: SiteTransform) -> dict:
    """Return {space_global_id: {"name", "centroid"}} for IfcSpaces overlapping pipe_z.

    Centroid is the mean of the space mesh vertices, forced to the routing
    elevation, in site-aligned coords. Used by the resolver for `room` anchors
    (decision #10: centroid → nearest passable voxel).
    """
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    spaces = {}
    for space in model.by_type("IfcSpace"):
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            if len(verts) == 0:
                continue
            z = verts[:, 2]
            if z.max() < pipe_z - 0.5 or z.min() > pipe_z + 0.5:
                continue
            world_c = verts.mean(axis=0)
            world_c[2] = pipe_z
            site_c = site_xform.to_site(world_c.reshape(1, 3))[0]
            spaces[space.GlobalId] = {
                "name": (space.Name or "").strip(),
                "centroid": site_c,
            }
        except Exception as e:
            logger.debug("Space geometry failed for %s: %s", space.GlobalId, e)

    return spaces


def _element_on_storey(element, storey: StoreyInfo, model) -> bool:
    """Check if an element is contained within the given storey.

    Handles two cases:
    - Element directly in IfcBuildingStorey (walls, slabs, columns)
    - Element in IfcSpace which aggregates into IfcBuildingStorey (flow terminals)
    """
    import ifcopenshell.util.element
    try:
        container = ifcopenshell.util.element.get_container(element)
        if container is None:
            return False
        if container.is_a("IfcBuildingStorey"):
            return container.id() == storey.id
        # Element is in a space — walk up via IfcRelAggregates
        if container.is_a("IfcSpace"):
            for rel in getattr(container, "Decomposes", []):
                parent = rel.RelatingObject
                if parent.is_a("IfcBuildingStorey") and parent.id() == storey.id:
                    return True
        return False
    except Exception:
        return False


def _get_elevation(storey, unit_scale: float = 1.0) -> float:
    """Extract storey elevation in metres, applying project-unit → metre conversion."""
    try:
        if storey.Elevation is not None:
            return float(storey.Elevation) * unit_scale
    except Exception:
        pass
    try:
        import ifcopenshell.util.placement
        matrix = ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)
        return float(matrix[2, 3]) * unit_scale
    except Exception:
        return 0.0


def _shape_to_trimesh(shape):
    """Convert an ifcopenshell shape to a trimesh.Trimesh."""
    import trimesh

    geo = shape.geometry
    verts = np.array(geo.verts).reshape(-1, 3)
    faces = np.array(geo.faces).reshape(-1, 3)
    if len(verts) == 0 or len(faces) == 0:
        return None
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _compute_xy_bounds(meshes: list) -> tuple[np.ndarray, np.ndarray]:
    """Compute combined XY bounding box across all meshes."""
    import trimesh

    if not meshes:
        return np.zeros(2), np.ones(2)

    combined = trimesh.util.concatenate(meshes)
    b = combined.bounds  # [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    return b[0, :2].copy(), b[1, :2].copy()
