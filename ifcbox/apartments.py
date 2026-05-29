"""Apartment discovery.

Group the rooms reachable from each hallway (Flur) **without crossing a
fire-rated wall** — the real apartment / compartment boundary. Built from an
IfcDoor adjacency graph: each door connects the two spaces it samples into; a
door set in a fire-rated wall makes that edge a non-traversable boundary.

See plans/spec-frontend.md §10. Used by the API (apartments.json at prepare).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque

import numpy as np

from ifcbox.pipeline.zoning import FORBIDDEN_PATTERNS, PREFERRED_CORRIDOR_PATTERNS
from ifcbox.wall_attrs import wall_fire_rating

_EXTERNAL_RE = re.compile(r"^\s*(balkon|terrasse|balcony|terrace|loggia)", re.IGNORECASE)

logger = logging.getLogger(__name__)

_DOOR_SAMPLE_M = 0.35   # sample this far either side of a door, perpendicular to it


def _space_polygon(space, settings, site_xform, z):
    """True (non-convex) section polygon of a space at z, in site-aligned XY.

    Uses the section's actual outline rather than the convex hull, so L-shaped
    rooms and balcony-attached living rooms don't over-extend into neighbours
    and falsely link apartments via the open-plan adjacency rule.
    """
    import ifcopenshell.geom
    import trimesh
    from shapely.geometry import Polygon

    try:
        shape = ifcopenshell.geom.create_shape(settings, space)
        verts = np.array(shape.geometry.verts).reshape(-1, 3)
        faces = np.array(shape.geometry.faces).reshape(-1, 3)
        if len(verts) == 0:
            return None
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh = site_xform.transform_mesh(mesh)
        sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None:
            return None
        loops = []
        for loop in sec.discrete:
            if len(loop) < 3:
                continue
            try:
                p = Polygon(loop[:, :2])
                if p.is_valid and p.area > 0:
                    loops.append(p)
            except Exception:
                pass
        if not loops:
            return None
        poly = max(loops, key=lambda p: p.area)
        return poly if poly.area >= 0.05 else None
    except Exception:
        return None


def _door_host_wall(door):
    """IfcDoor → its opening → the host wall (or None)."""
    for rel in getattr(door, "FillsVoids", []):
        opening = rel.RelatingOpeningElement
        for vrel in getattr(opening, "VoidsElements", []):
            return vrel.RelatingBuildingElement
    return None


def discover_apartments(model, storey, site_xform) -> list[dict]:
    """Return [{flur_id, flur_name, room_ids}] for each apartment on the storey."""
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    from shapely.geometry import Point

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    z = storey.elevation + 1.0

    polys: dict[str, object] = {}
    names: dict[str, str] = {}
    for space in model.by_type("IfcSpace"):
        if not any(rel.RelatingObject.id() == storey.id
                   for rel in getattr(space, "Decomposes", [])):
            continue
        poly = _space_polygon(space, settings, site_xform, z)
        if poly is None:
            continue
        polys[space.GlobalId] = poly
        names[space.GlobalId] = (space.Name or "").strip()

    adjacency: dict[str, set] = defaultdict(set)
    fire_edges: set[frozenset] = set()

    # Open-plan adjacency thresholds (mirror demo_routes.build_door_adjacency):
    # polygons closer than _OPEN_GAP (< thinnest partition, so walls still block)
    # and sharing ≥ _OPEN_MIN_SHARED of boundary count as a door-less opening.
    _OPEN_GAP = 0.12
    _OPEN_MIN_SHARED = 0.40

    doors = [d for d in model.by_type("IfcDoor")
             if (c := ifcopenshell.util.element.get_container(d)) is not None
             and c.id() == storey.id]
    for door in doors:
        try:
            mat = ifcopenshell.util.placement.get_local_placement(door.ObjectPlacement)
            pos = site_xform.to_site(mat[:3, 3].reshape(1, 3))[0][:2]
            x_axis = (site_xform.site_matrix[:3, :3] @ mat[:3, 0])[:2]
            x_axis = x_axis / (np.linalg.norm(x_axis) + 1e-9)
            normal = np.array([-x_axis[1], x_axis[0]])
            a = next((g for g, p in polys.items() if p.contains(Point(pos + _DOOR_SAMPLE_M * normal))), None)
            b = next((g for g, p in polys.items() if p.contains(Point(pos - _DOOR_SAMPLE_M * normal))), None)
            if not (a and b) or a == b:
                continue
            adjacency[a].add(b)
            adjacency[b].add(a)
            wall = _door_host_wall(door)
            if wall is not None and wall_fire_rating(wall) != "—":
                fire_edges.add(frozenset((a, b)))
        except Exception:
            continue

    # Open-plan / door-less openings — two polygons close enough that there is
    # no wall between them. These are inherently not fire-rated (no wall to host
    # a rating); they only ever add traversable edges, never fire_edges.
    gids = list(polys.keys())
    for i, a in enumerate(gids):
        pa = polys[a]
        for b in gids[i + 1:]:
            if b in adjacency.get(a, ()):
                continue
            pb = polys[b]
            if pa.distance(pb) > _OPEN_GAP:
                continue
            shared = pa.buffer(_OPEN_GAP / 2).intersection(pb.buffer(_OPEN_GAP / 2))
            shared_len = shared.length if not shared.is_empty else 0.0
            if shared_len >= _OPEN_MIN_SHARED:
                adjacency[a].add(b)
                adjacency[b].add(a)

    is_flur = lambda nm: bool(PREFERRED_CORRIDOR_PATTERNS.match(nm))
    is_forbidden = lambda nm: bool(FORBIDDEN_PATTERNS.match(nm))
    is_external = lambda nm: bool(_EXTERNAL_RE.match(nm))

    # BFS per Flur — Flurs and forbidden zones (stairwells / shafts) act as soft
    # boundaries: not crossed, not listed. Fire-rated edges block traversal.
    # Balconies / terrasses are reachable but not useful destinations.
    apartments: list[dict] = []
    for flur in sorted(g for g in polys if is_flur(names[g])):
        visited = {flur}
        dq = deque([flur])
        rooms: list[str] = []
        while dq:
            cur = dq.popleft()
            for nb in adjacency.get(cur, ()):
                if nb in visited:
                    continue
                if frozenset((cur, nb)) in fire_edges:
                    continue
                visited.add(nb)
                nm = names.get(nb, "")
                if is_forbidden(nm) or is_flur(nm):
                    continue   # don't traverse through, don't list
                dq.append(nb)
                if not is_external(nm):
                    rooms.append(nb)
        if rooms:
            apartments.append({
                "flur_id": flur,
                "flur_name": names[flur],
                "room_ids": rooms,
                "room_names": [names[g] for g in rooms],
            })

    logger.info("Discovered %d apartments on storey '%s'", len(apartments), storey.name)
    return apartments
