"""Apartment discovery.

Group the rooms reachable from each hallway (Flur) **without crossing a
fire-rated wall** — the real apartment / compartment boundary. Built from an
IfcDoor adjacency graph: each door connects the two spaces it samples into; a
door set in a fire-rated wall makes that edge a non-traversable boundary.

See plans/spec-frontend.md §10. Used by the API (apartments.json at prepare).
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque

import numpy as np

from ifcbox.pipeline.zoning import FORBIDDEN_PATTERNS, PREFERRED_CORRIDOR_PATTERNS
from ifcbox.wall_attrs import wall_fire_rating

logger = logging.getLogger(__name__)

_DOOR_SAMPLE_M = 0.35   # sample this far either side of a door, perpendicular to it


def _space_polygon(space, settings, site_xform, z):
    import ifcopenshell.geom
    import trimesh
    from shapely.geometry import MultiPoint

    try:
        shape = ifcopenshell.geom.create_shape(settings, space)
        verts = np.array(shape.geometry.verts).reshape(-1, 3)
        faces = np.array(shape.geometry.faces).reshape(-1, 3)
        if len(verts) == 0:
            return None
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh = site_xform.transform_mesh(mesh)
        sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None or len(sec.vertices) < 3:
            return None
        poly = MultiPoint(sec.vertices[:, :2]).convex_hull
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

    def open_neighbours(g):
        return [h for h in adjacency.get(g, ()) if frozenset((g, h)) not in fire_edges]

    is_flur = lambda nm: bool(PREFERRED_CORRIDOR_PATTERNS.match(nm))
    is_forbidden = lambda nm: bool(FORBIDDEN_PATTERNS.match(nm))

    apartments: list[dict] = []
    seen: set[str] = set()
    for start in polys:
        if start in seen:
            continue
        comp: list[str] = []
        dq = deque([start])
        seen.add(start)
        while dq:
            cur = dq.popleft()
            comp.append(cur)
            for nb in open_neighbours(cur):
                if nb not in seen:
                    seen.add(nb)
                    dq.append(nb)
        flurs = [g for g in comp if is_flur(names[g])]
        if not flurs:
            continue
        source = flurs[0]
        rooms = [g for g in comp if g != source and not is_forbidden(names[g])]
        if rooms:
            apartments.append({
                "flur_id": source,
                "flur_name": names[source],
                "room_ids": rooms,
                "room_names": [names[g] for g in rooms],
            })

    logger.info("Discovered %d apartments on storey '%s'", len(apartments), storey.name)
    return apartments
