"""
Rich debug visualisation.

Renders a floor plan with:
  - Colour-coded obstacle types (walls, slabs, columns, beams, stairs)
  - Corridor spaces highlighted
  - Door markers with wall-crossing zone indicators
  - Room / space name labels
  - Routed path overlay
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np

from .pipeline.voxelizer import VoxelMeta
from .pipeline.zoning import CIRCULATION_PATTERNS

logger = logging.getLogger(__name__)

# ── Colour scheme ─────────────────────────────────────────────────────────────

# Background / base layers
COLOUR_EXTERIOR   = "#1a1a1a"
COLOUR_FREE_ROOM  = "#f5f0e8"
COLOUR_CORRIDOR   = "#c8e6c9"   # light green — circulation space
COLOUR_BALCONY    = "#e8f4fd"   # light blue

# Obstacle types — drawn as coloured patches on the floor plan
OBSTACLE_COLOURS = {
    "IfcWallStandardCase": "#4a4a4a",
    "IfcWall":             "#4a4a4a",
    "IfcCurtainWall":      "#6a9fb5",
    "IfcSlab":             "#8d6e63",
    "IfcColumn":           "#e53935",
    "IfcBeam":             "#8e24aa",
    "IfcStair":            "#00897b",
    "IfcStairFlight":      "#00897b",
    "IfcRamp":             "#f9a825",
    "IfcRampFlight":       "#f9a825",
    "IfcRoof":             "#546e7a",
}
OBSTACLE_DEFAULT  = "#555555"

# Wall classification colours (override per-type obstacle colours)
COLOUR_WALL_PARTITION = "#9e9e9e"   # light grey   — lightweight internal partition
COLOUR_WALL_PARTY     = "#e65100"   # deep orange  — party / heavy wall
COLOUR_WALL_EXTERNAL  = "#263238"   # dark blue-grey — external / structural

# Forbidden zone overlay
COLOUR_FORBIDDEN  = "#b71c1c"       # deep red — Treppenraum / no-go areas

# Overlay / annotation colours
COLOUR_DOOR_ZONE  = "#ffd54f"       # amber yellow — door crossing zone
COLOUR_DOOR_MARK  = "#ff6f00"       # deep amber   — door marker line
COLOUR_ROUTE      = "#0052d5"       # blue — pipe route
COLOUR_WAYPOINT   = "#8b17ff"
COLOUR_ENDPOINT   = "#00d9ff"
COLOUR_LABEL      = "#212121"
COLOUR_CORR_LABEL = "#1b5e20"


# ── Public entry point ────────────────────────────────────────────────────────

def render_debug_scene(
    occupancy: np.ndarray,
    meta: VoxelMeta,
    model,
    storey,
    site_xform,
    corridor: np.ndarray,
    door_zone: np.ndarray,
    wall_costs: np.ndarray | None = None,
    forbidden: np.ndarray | None = None,
    waypoints: list[np.ndarray] | None = None,
    output_path: str = "output/debug_scene.png",
):
    """
    Render a rich floor-plan debug image.

    model, storey, site_xform are used to extract per-type obstacle colours,
    door markers, and room labels.
    """
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba

    nx, ny = meta.shape
    fig, ax = plt.subplots(figsize=(20, 10))
    ax.set_facecolor(COLOUR_EXTERIOR)
    fig.patch.set_facecolor("#ffffff")

    # ── Layer 1: free-space base ──────────────────────────────────────────────
    free_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
    free = ~occupancy

    # Default free colour
    r, g, b, _ = to_rgba(COLOUR_FREE_ROOM)
    free_rgba[free.T, :3] = [r, g, b]
    free_rgba[free.T, 3] = 1.0

    # Corridor overlay — tint green where corridor membership is set
    corr = corridor & free
    cr, cg, cb, _ = to_rgba(COLOUR_CORRIDOR)
    free_rgba[corr.T, :3] = [cr, cg, cb]
    free_rgba[corr.T, 3] = 1.0

    ax.imshow(free_rgba, origin="lower", interpolation="nearest",
              extent=[0, nx, 0, ny])

    # ── Layer 2: obstacles coloured by IFC type ───────────────────────────────
    _draw_obstacle_layers(ax, model, meta, storey, site_xform, nx, ny)

    # ── Layer 3: forbidden zones (Treppenraum etc.) ───────────────────────────
    if forbidden is not None and forbidden.any():
        forb_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        fr, fg, fb, _ = to_rgba(COLOUR_FORBIDDEN)
        forb_rgba[forbidden.T, :] = [fr, fg, fb, 0.35]
        ax.imshow(forb_rgba, origin="lower", interpolation="nearest",
                  extent=[0, nx, 0, ny])

    # ── Layer 4: door crossing zones ─────────────────────────────────────────
    reduced = occupancy & door_zone
    if reduced.any():
        door_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        dr, dg, db, _ = to_rgba(COLOUR_DOOR_ZONE)
        door_rgba[reduced.T, :] = [dr, dg, db, 0.9]
        ax.imshow(door_rgba, origin="lower", interpolation="nearest",
                  extent=[0, nx, 0, ny])

    # ── Layer 4: door position markers ───────────────────────────────────────
    _draw_door_markers(ax, model, meta, storey, site_xform)

    # ── Layer 5: room labels ──────────────────────────────────────────────────
    _draw_room_labels(ax, model, meta, storey, site_xform)

    # ── Layer 6: route ───────────────────────────────────────────────────────
    if waypoints and len(waypoints) >= 2:
        vxs = [meta.world_to_voxel(wp[:2])[0] for wp in waypoints]
        vys = [meta.world_to_voxel(wp[:2])[1] for wp in waypoints]
        ax.plot(vxs, vys, color=COLOUR_ROUTE, linewidth=2.5, zorder=10)
        # Bend points
        for x, y in zip(vxs[1:-1], vys[1:-1]):
            ax.plot(x, y, "o", color=COLOUR_WAYPOINT, markersize=6, zorder=11)
        # Endpoints
        for x, y in [(vxs[0], vys[0]), (vxs[-1], vys[-1])]:
            ax.plot(x, y, "D", color=COLOUR_ENDPOINT, markersize=10, zorder=12)

    # ── Legend ────────────────────────────────────────────────────────────────
    from .pipeline.loader import OBSTACLE_TYPES
    DRAW_ORDER = [
        "IfcRamp", "IfcRampFlight", "IfcStair", "IfcStairFlight",
        "IfcCurtainWall", "IfcWall", "IfcWallStandardCase",
        "IfcBeam", "IfcColumn",
    ]
    legend_items = [mpatches.Patch(color=COLOUR_CORRIDOR, label="Corridor / Flur")]
    for t in DRAW_ORDER:
        if t in OBSTACLE_TYPES:
            legend_items.append(
                mpatches.Patch(color=OBSTACLE_COLOURS.get(t, OBSTACLE_DEFAULT),
                               label=t.replace("Ifc", ""))
            )
    legend_items += [
        mpatches.Patch(color=COLOUR_DOOR_ZONE,  label="Door crossing zone"),
        mpatches.Patch(color=COLOUR_FORBIDDEN,  label="Forbidden zone", alpha=0.5),
    ]
    if waypoints:
        legend_items.append(mpatches.Patch(color=COLOUR_ROUTE, label="Route"))
    ax.legend(handles=legend_items, loc="upper right", fontsize=7,
              framealpha=0.9, ncol=2)

    ax.set_title(
        f"IFCBox debug — {storey.name}  |  {nx}×{ny} @ {meta.resolution*1000:.0f}mm",
        fontsize=11,
    )
    ax.set_xlim(0, nx)
    ax.set_ylim(0, ny)
    ax.set_aspect("equal")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved rich debug scene: %s", output_path)


# ── Private drawing helpers ───────────────────────────────────────────────────


def _draw_wall_thickness_layer(ax, fig, model, storey, site_xform, meta, nx, ny) -> None:
    """Colour wall voxels by actual thickness from IfcMaterialLayerSet (plasma scale)."""
    import matplotlib.cm as mcm
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    items = [(_wall_total_thickness(el), mask)
             for el, mask in _iter_wall_rasters(model, storey, site_xform, meta)]

    known   = [(t, mask) for t, mask in items if t is not None]
    unknown = [mask      for t, mask in items if t is None]

    cmap = mcm.get_cmap("plasma")
    if known:
        t_min = min(t for t, _ in known)
        t_max = max(t for t, _ in known)
        norm = Normalize(vmin=t_min, vmax=max(t_max, t_min + 0.001))
    else:
        norm = Normalize(vmin=0, vmax=1)

    for mask in unknown:
        rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        rgba[mask.T, :] = [0.35, 0.35, 0.35, 1.0]
        ax.imshow(rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    for t, mask in known:
        rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        rv, gv, bv, _ = cmap(norm(t))
        rgba[mask.T, :] = [rv, gv, bv, 1.0]
        ax.imshow(rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, fraction=0.015, pad=0.01)
    cb.set_label("Wall thickness (m)", fontsize=8)


def _draw_nonwall_obstacle_layers(ax, model, meta, storey, site_xform, nx, ny):
    """Draw columns, slabs, stairs etc. on top of wall classification layer."""
    import ifcopenshell.geom
    import trimesh
    from matplotlib.colors import to_rgba

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    pipe_z = storey.elevation + 2.5
    z_lo = pipe_z - 0.5
    z_hi = pipe_z + 0.5

    nonwall_types = [
        ("IfcColumn",      OBSTACLE_COLOURS["IfcColumn"]),
        ("IfcBeam",        OBSTACLE_COLOURS["IfcBeam"]),
        ("IfcStair",       OBSTACLE_COLOURS["IfcStair"]),
        ("IfcStairFlight", OBSTACLE_COLOURS["IfcStairFlight"]),
        ("IfcCurtainWall", OBSTACLE_COLOURS["IfcCurtainWall"]),
    ]

    from .pipeline.voxelizer import _rasterize_section_3d

    for ifc_type, colour in nonwall_types:
        layer = np.zeros((nx, ny), dtype=bool)
        for element in model.by_type(ifc_type):
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
                verts = np.array(shape.geometry.verts).reshape(-1, 3)
                faces = np.array(shape.geometry.faces).reshape(-1, 3)
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
                mesh = site_xform.transform_mesh(mesh)
                zn, zx = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
                if zx < z_lo or zn > z_hi:
                    continue
                section = mesh.section(plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1])
                if section is not None and len(section.vertices) >= 3:
                    _rasterize_section_3d(section, layer, meta)
            except Exception:
                continue
        if layer.any():
            r, g, b, _ = to_rgba(colour)
            rgba = np.zeros((ny, nx, 4), dtype=np.float32)
            rgba[layer.T, :] = [r, g, b, 1.0]
            ax.imshow(rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])


def _draw_obstacle_layers(ax, model, meta, storey, site_xform, nx, ny):
    """Draw one coloured raster layer per active obstacle IFC type."""
    import ifcopenshell.geom
    import trimesh
    from matplotlib.colors import to_rgba

    from .pipeline.loader import OBSTACLE_TYPES
    from .pipeline.voxelizer import _rasterize_section_3d

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    pipe_z = storey.elevation + 2.5
    z_lo = pipe_z - 0.5
    z_hi = pipe_z + 0.5

    # Draw order: larger/background elements first, small elements on top
    DRAW_ORDER = [
        "IfcRamp", "IfcRampFlight",
        "IfcStair", "IfcStairFlight",
        "IfcCurtainWall", "IfcWall", "IfcWallStandardCase",
        "IfcBeam", "IfcColumn",
    ]
    type_order = [t for t in DRAW_ORDER if t in OBSTACLE_TYPES]

    for ifc_type in type_order:
        colour = OBSTACLE_COLOURS.get(ifc_type, OBSTACLE_DEFAULT)
        layer = np.zeros((nx, ny), dtype=bool)

        for element in model.by_type(ifc_type):
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
                verts = np.array(shape.geometry.verts).reshape(-1, 3)
                faces = np.array(shape.geometry.faces).reshape(-1, 3)
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
                mesh = site_xform.transform_mesh(mesh)
                zn, zx = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
                if zx < z_lo or zn > z_hi:
                    continue
                section = mesh.section(
                    plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1]
                )
                if section is not None and len(section.vertices) >= 3:
                    _rasterize_section_3d(section, layer, meta)
            except Exception:
                continue

        if layer.any():
            r, g, b, _ = to_rgba(colour)
            rgba = np.zeros((ny, nx, 4), dtype=np.float32)
            rgba[layer.T, :] = [r, g, b, 1.0]
            ax.imshow(rgba, origin="lower", interpolation="nearest",
                      extent=[0, nx, 0, ny])


def _draw_door_markers(ax, model, meta, storey, site_xform):
    """Draw diamond markers at each door position on this storey."""
    import ifcopenshell.util.element
    import ifcopenshell.util.placement

    for door in model.by_type("IfcDoor"):
        try:
            container = ifcopenshell.util.element.get_container(door)
            if container is None or container.id() != storey.id:
                continue
            mat = ifcopenshell.util.placement.get_local_placement(door.ObjectPlacement)
            world_pos = mat[:3, 3]
            site_pos = site_xform.to_site(world_pos.reshape(1, 3))[0]
            vx, vy = meta.world_to_voxel(site_pos[:2])

            # Door width direction in site coords
            rot3 = site_xform.site_matrix[:3, :3]
            site_x = rot3 @ mat[:3, 0]
            site_x = site_x[:2]
            site_x /= np.linalg.norm(site_x) + 1e-9

            w = getattr(door, "OverallWidth", 0.9) or 0.9
            half_w_vx = (w / 2) / meta.resolution

            # Draw door as a short thick line across the wall opening
            dx, dy = site_x
            ax.plot(
                [vx - half_w_vx * dx, vx + half_w_vx * dx],
                [vy - half_w_vx * dy, vy + half_w_vx * dy],
                color=COLOUR_DOOR_MARK, linewidth=2.5, solid_capstyle="round",
                zorder=7,
            )
        except Exception:
            continue


def _wall_type_name(element) -> str:
    """Return IfcWallType name, falling back to element name or 'Unknown'."""
    try:
        import ifcopenshell.util.element
        wtype = ifcopenshell.util.element.get_type(element)
        if wtype is not None:
            n = (wtype.Name or "").strip()
            if n:
                return n
    except Exception:
        pass
    return (element.Name or "").strip() or "Unknown"


def _wall_fire_rating(element) -> str:
    """
    Return FireRating by walking IsDefinedBy directly.
    get_psets() skips null NominalValue; this handles that case explicitly.
    """
    try:
        for rel in getattr(element, "IsDefinedBy", []):
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if not pset.is_a("IfcPropertySet"):
                continue
            for prop in pset.HasProperties:
                if prop.Name == "FireRating":
                    nv = prop.NominalValue
                    if nv is not None:
                        s = str(nv.wrappedValue).strip()
                        return s if s else "—"
    except Exception:
        pass
    return "—"


def _wall_total_thickness(element) -> float | None:
    """
    Return wall thickness in metres from IfcMaterialLayerSet on the element
    or its IfcWallType.  Falls back to Qto_WallBaseQuantities.Width.
    """
    def _from_associations(entity) -> float | None:
        for rel in getattr(entity, "HasAssociations", []):
            if not rel.is_a("IfcRelAssociatesMaterial"):
                continue
            mat = rel.RelatingMaterial
            if mat.is_a("IfcMaterialLayerSet"):
                return sum(l.LayerThickness for l in mat.MaterialLayers)
            if mat.is_a("IfcMaterialLayerSetUsage"):
                return sum(l.LayerThickness for l in mat.ForLayerSet.MaterialLayers)
        return None

    try:
        t = _from_associations(element)
        if t is not None:
            return t
        import ifcopenshell.util.element
        wtype = ifcopenshell.util.element.get_type(element)
        if wtype is not None:
            t = _from_associations(wtype)
            if t is not None:
                return t
        w = ifcopenshell.util.element.get_psets(element).get(
            "Qto_WallBaseQuantities", {}
        ).get("Width")
        if w is not None:
            return float(w)
    except Exception:
        pass
    return None


def _iter_wall_rasters(model, storey, site_xform, meta):
    """
    Yield (element, bool_mask_2d) for each IfcWall/IfcWallStandardCase whose
    geometry intersects the routing elevation on this storey.
    """
    import ifcopenshell.geom
    import trimesh

    from .pipeline.voxelizer import _rasterize_section_3d

    nx, ny = meta.shape
    pipe_z = storey.elevation + 2.5
    z_lo = pipe_z - 0.5
    z_hi = pipe_z + 0.5

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    for ifc_type in ("IfcWall", "IfcWallStandardCase"):
        for element in model.by_type(ifc_type):
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
                verts = np.array(shape.geometry.verts).reshape(-1, 3)
                faces = np.array(shape.geometry.faces).reshape(-1, 3)
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
                mesh = site_xform.transform_mesh(mesh)
                zn, zx = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
                if zx < z_lo or zn > z_hi:
                    continue
                section = mesh.section(plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1])
                if section is None or len(section.vertices) < 3:
                    continue
                mask = np.zeros((nx, ny), dtype=bool)
                _rasterize_section_3d(section, mask, meta)
                if mask.any():
                    yield element, mask
            except Exception:
                continue


def _overlay_route(ax, waypoints, meta):
    if not waypoints or len(waypoints) < 2:
        return
    vxs = [meta.world_to_voxel(wp[:2])[0] for wp in waypoints]
    vys = [meta.world_to_voxel(wp[:2])[1] for wp in waypoints]
    ax.plot(vxs, vys, color=COLOUR_ROUTE, linewidth=2.5, zorder=10)
    for x, y in zip(vxs[1:-1], vys[1:-1]):
        ax.plot(x, y, "o", color=COLOUR_WAYPOINT, markersize=5, zorder=11)
    for x, y in [(vxs[0], vys[0]), (vxs[-1], vys[-1])]:
        ax.plot(x, y, "D", color=COLOUR_ENDPOINT, markersize=9, zorder=12)


def render_wall_typename_debug(
    model,
    storey,
    site_xform,
    meta: VoxelMeta,
    output_path: str = "output/debug_wall_typenames.png",
    waypoints: list | None = None,
) -> None:
    """
    Debug PNG: each wall voxel coloured by its IfcWallType name.
    Uses tab20 palette; walls with no type shown as 'Unknown'.
    """
    import matplotlib.cm as mcm
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    nx, ny = meta.shape

    # One pass: collect (name, mask) for every wall
    name_masks: list[tuple[str, np.ndarray]] = [
        (_wall_type_name(el), mask)
        for el, mask in _iter_wall_rasters(model, storey, site_xform, meta)
    ]

    unique_names = sorted(set(n for n, _ in name_masks))
    cmap = mcm.get_cmap("tab20")
    colour_map = {n: cmap(i % 20 / 20) for i, n in enumerate(unique_names)}

    fig, ax = plt.subplots(figsize=(20, 10))
    ax.set_facecolor(COLOUR_EXTERIOR)
    fig.patch.set_facecolor("#ffffff")

    for name, mask in name_masks:
        rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        r, g, b, _ = colour_map[name]
        rgba[mask.T, :] = [r, g, b, 1.0]
        ax.imshow(rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    _overlay_route(ax, waypoints, meta)

    ncol = 2 if len(unique_names) > 8 else 1
    ax.legend(
        handles=[mpatches.Patch(color=colour_map[n], label=n) for n in unique_names],
        loc="upper right", fontsize=6, framealpha=0.92, ncol=ncol,
    )
    ax.set_title(
        f"IFCBox — IfcWallType names — {storey.name}  |  {nx}×{ny} @ {meta.resolution*1000:.0f}mm",
        fontsize=11,
    )
    ax.set_xlim(0, nx); ax.set_ylim(0, ny); ax.set_aspect("equal")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved wall type-name debug: %s", output_path)


def render_wall_properties_debug(
    model,
    storey,
    site_xform,
    meta: VoxelMeta,
    output_path: str = "output/debug_wall_properties.png",
    waypoints: list | None = None,
) -> None:
    """
    Debug PNG (2-panel): left = FireRating (categorical), right = TotalThickness (continuous).
    Both sourced from Pset_WallCommon.
    """
    import matplotlib.cm as mcm
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    nx, ny = meta.shape

    # One pass over walls — collect fire rating, thickness, mask
    rows: list[tuple[str, float | None, np.ndarray]] = [
        (_wall_fire_rating(el), _wall_total_thickness(el), mask)
        for el, mask in _iter_wall_rasters(model, storey, site_xform, meta)
    ]

    fig, axes = plt.subplots(1, 2, figsize=(30, 12))
    fig.patch.set_facecolor("#ffffff")

    # ── Left: fire rating ─────────────────────────────────────────────────────
    ax_fr = axes[0]
    ax_fr.set_facecolor(COLOUR_EXTERIOR)

    unique_ratings = sorted(set(fr for fr, _, _ in rows))
    cmap_cat = mcm.get_cmap("tab10")
    fr_colour = {r: cmap_cat(i % 10 / 10) for i, r in enumerate(unique_ratings)}

    for fr, _, mask in rows:
        rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        rv, gv, bv, _ = fr_colour[fr]
        rgba[mask.T, :] = [rv, gv, bv, 1.0]
        ax_fr.imshow(rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    _overlay_route(ax_fr, waypoints, meta)
    ax_fr.legend(
        handles=[mpatches.Patch(color=fr_colour[r], label=r) for r in unique_ratings],
        loc="upper right", fontsize=7, framealpha=0.92,
    )
    ax_fr.set_title(f"Pset_WallCommon.FireRating — {storey.name}", fontsize=10)
    ax_fr.set_xlim(0, nx); ax_fr.set_ylim(0, ny); ax_fr.set_aspect("equal")

    # ── Right: total thickness ────────────────────────────────────────────────
    ax_th = axes[1]
    ax_th.set_facecolor(COLOUR_EXTERIOR)

    thickness_vals = [th for _, th, _ in rows if th is not None]
    cmap_cont = mcm.get_cmap("plasma")
    if thickness_vals:
        norm = Normalize(vmin=min(thickness_vals), vmax=max(thickness_vals))
    else:
        norm = Normalize(vmin=0, vmax=1)

    for _, th, mask in rows:
        rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        if th is not None:
            rv, gv, bv, _ = cmap_cont(norm(th))
        else:
            rv, gv, bv = 0.45, 0.45, 0.45   # grey = no data
        rgba[mask.T, :] = [rv, gv, bv, 1.0]
        ax_th.imshow(rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    _overlay_route(ax_th, waypoints, meta)

    sm = plt.cm.ScalarMappable(cmap=cmap_cont, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax_th, fraction=0.03, pad=0.02)
    cb.set_label("TotalThickness (m)", fontsize=9)
    if not thickness_vals:
        ax_th.text(0.5, 0.5, "No TotalThickness data in model",
                   transform=ax_th.transAxes, ha="center", va="center",
                   fontsize=12, color="white")
    ax_th.set_title(f"Pset_WallCommon.TotalThickness — {storey.name}", fontsize=10)
    ax_th.set_xlim(0, nx); ax_th.set_ylim(0, ny); ax_th.set_aspect("equal")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved wall properties debug: %s", output_path)


def _draw_room_labels(ax, model, meta, storey, site_xform):
    """Draw space name labels at each room centroid on this storey."""
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import trimesh

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    pipe_z = storey.elevation + 2.5

    for space in model.by_type("IfcSpace"):
        # Only spaces that aggregate into this storey
        on_storey = False
        for rel in getattr(space, "Decomposes", []):
            if rel.RelatingObject.id() == storey.id:
                on_storey = True
                break
        if not on_storey:
            continue

        name = (space.Name or "").split(":")[0].strip()  # strip IFC id suffix
        if not name:
            continue

        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            faces = np.array(shape.geometry.faces).reshape(-1, 3)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            mesh = site_xform.transform_mesh(mesh)

            zn, zx = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
            if zx < pipe_z - 3.0 or zn > pipe_z + 1.0:
                continue

            # Centroid of 2D bounding box
            cx = (mesh.bounds[0][0] + mesh.bounds[1][0]) / 2
            cy = (mesh.bounds[0][1] + mesh.bounds[1][1]) / 2
            vx, vy = meta.world_to_voxel(np.array([cx, cy]))

            is_circ = bool(CIRCULATION_PATTERNS.match(name))
            colour = COLOUR_CORR_LABEL if is_circ else COLOUR_LABEL
            weight = "bold" if is_circ else "normal"

            ax.text(
                vx, vy, name,
                fontsize=5, color=colour, fontweight=weight,
                ha="center", va="center", zorder=9,
                bbox=dict(
                    boxstyle="round,pad=0.15",
                    facecolor="white", edgecolor="none", alpha=0.65,
                ),
            )
        except Exception:
            continue
