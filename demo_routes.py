#!/usr/bin/env python3
"""
Demo: route from each apartment Flur centroid to nearest adjacent space centroid.
Constraints: strict door crossings only, no routing through Treppenraum.

Outputs per route: output/route_<n>_debug_scene.png, route_<n>.json, pipe_<n>.glb
Final:             output/debug_scene_all_routes.png  (all routes overlaid)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ifcbox.demo")


def get_space_polygon(space, settings, site_xform, sample_z):
    """
    Return a Shapely polygon for the space footprint at sample_z, in site-aligned
    coordinates. Uses the polygon's representative_point() for centroid — guaranteed
    to be inside the polygon even for L-shaped or concave spaces.

    Returns (polygon, representative_point_xy) or (None, None).
    """
    import ifcopenshell.geom
    import trimesh
    from shapely.geometry import MultiPoint

    try:
        shape = ifcopenshell.geom.create_shape(settings, space)
        verts = np.array(shape.geometry.verts).reshape(-1, 3)
        mesh = trimesh.Trimesh(vertices=verts,
                               faces=np.array(shape.geometry.faces).reshape(-1, 3),
                               process=False)
        mesh = site_xform.transform_mesh(mesh)
        sec = mesh.section(plane_origin=[0, 0, sample_z], plane_normal=[0, 0, 1])
        if sec is None or len(sec.vertices) < 3:
            return None, None
        xy = sec.vertices[:, :2]
        poly = MultiPoint(xy).convex_hull
        if poly.area < 0.05:
            return None, None
        rp = poly.representative_point()
        return poly, np.array([rp.x, rp.y])
    except Exception:
        return None, None


def build_door_adjacency(model, storey, site_xform=None):
    """
    Build a space adjacency graph from door positions.

    For each IfcDoor on the storey, sample a point 300mm either side of the
    door (perpendicular to the wall face) and check which IfcSpace polygon
    contains each sample. Bidirectional edges are added to the adjacency graph.

    Returns:
        adjacency  : {space_GlobalId: set of adjacent space_GlobalIds}
        space_info : {space_GlobalId: space_name}
    """
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    import trimesh
    from collections import defaultdict
    from shapely.geometry import MultiPoint, Point

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    # ── 1. Build space footprint polygons ─────────────────────────────────────
    # Use site-aligned coords if site_xform provided, else world coords.
    # representative_point() guarantees the centroid is inside the polygon.
    sample_z = storey.elevation + 1.0
    space_polys  = {}   # GlobalId → shapely polygon  (for adjacency checks)
    space_info   = {}   # GlobalId → name
    space_points = {}   # GlobalId → site-aligned [x, y] representative point

    for space in model.by_type("IfcSpace"):
        on_floor = any(rel.RelatingObject.id() == storey.id
                       for rel in getattr(space, "Decomposes", []))
        if not on_floor:
            continue
        name = (space.Name or "").strip()

        if site_xform is not None:
            poly, rp = get_space_polygon(space, settings, site_xform, sample_z)
        else:
            # Fallback: world-coord polygon (door sampling still works)
            try:
                shape = ifcopenshell.geom.create_shape(settings, space)
                verts = np.array(shape.geometry.verts).reshape(-1, 3)
                mesh = trimesh.Trimesh(vertices=verts,
                                       faces=np.array(shape.geometry.faces).reshape(-1,3),
                                       process=False)
                sec = mesh.section(plane_origin=[0,0,sample_z], plane_normal=[0,0,1])
                if sec is None or len(sec.vertices) < 3:
                    continue
                poly = MultiPoint(sec.vertices[:,:2]).convex_hull
                rp = np.array([poly.representative_point().x,
                                poly.representative_point().y]) if poly.area > 0.05 else None
            except Exception:
                poly, rp = None, None

        if poly is None or rp is None:
            continue
        space_polys[space.GlobalId]  = poly
        space_info[space.GlobalId]   = name
        space_points[space.GlobalId] = rp

    logger.info("Built %d space footprints for door adjacency", len(space_polys))

    # ── 2. Sample each door — find spaces on both sides ───────────────────────
    adjacency = defaultdict(set)
    SAMPLE_DIST = 0.35  # metres from door centre, perpendicular to wall

    doors_on_storey = [
        d for d in model.by_type("IfcDoor")
        if (c := ifcopenshell.util.element.get_container(d)) is not None
        and c.id() == storey.id
    ]
    door_hits = 0
    for door in doors_on_storey:
        try:
            mat = ifcopenshell.util.placement.get_local_placement(door.ObjectPlacement)
            world_pos = mat[:3, 3]

            # Transform door position and axis to same coord system as space_polys
            if site_xform is not None:
                site_pos = site_xform.to_site(world_pos.reshape(1, 3))[0]
                pos_xy = site_pos[:2]
                rot3 = site_xform.site_matrix[:3, :3]
                x_axis = (rot3 @ mat[:3, 0])[:2]
            else:
                pos_xy = world_pos[:2]
                x_axis = mat[:2, 0]

            x_axis /= np.linalg.norm(x_axis) + 1e-9
            wall_normal = np.array([-x_axis[1], x_axis[0]])

            pt_a = Point(pos_xy + SAMPLE_DIST * wall_normal)
            pt_b = Point(pos_xy - SAMPLE_DIST * wall_normal)

            gid_a = next((gid for gid, poly in space_polys.items()
                          if poly.contains(pt_a)), None)
            gid_b = next((gid for gid, poly in space_polys.items()
                          if poly.contains(pt_b)), None)

            if gid_a and gid_b and gid_a != gid_b:
                adjacency[gid_a].add(gid_b)
                adjacency[gid_b].add(gid_a)
                door_hits += 1
        except Exception:
            continue

    logger.info("Door adjacency: %d/%d doors produced space edges",
                door_hits, len(doors_on_storey))

    # ── 3. Geometric adjacency — spaces with no wall between them ─────────────
    # Two space polygons within OPEN_GAP of each other share an opening (no door
    # required). This catches Flurs that open directly into a room.
    # Threshold is kept small (< thinnest partition) to avoid false connections.
    OPEN_GAP    = 0.12   # metres — max gap for "open" connection (< 150mm partition)
    MIN_SHARED  = 0.40   # minimum shared boundary length to count as a real opening

    gids = list(space_polys.keys())
    open_hits = 0
    for i, gid_a in enumerate(gids):
        poly_a = space_polys[gid_a]
        for gid_b in gids[i + 1:]:
            if gid_b in adjacency.get(gid_a, set()):
                continue  # already connected via door
            poly_b = space_polys[gid_b]
            if poly_a.distance(poly_b) > OPEN_GAP:
                continue
            # Measure shared boundary length via buffered intersection
            shared = poly_a.buffer(OPEN_GAP / 2).intersection(poly_b.buffer(OPEN_GAP / 2))
            shared_len = shared.length if not shared.is_empty else 0.0
            if shared_len >= MIN_SHARED:
                adjacency[gid_a].add(gid_b)
                adjacency[gid_b].add(gid_a)
                open_hits += 1
                logger.debug("Open adjacency: %r ↔ %r (gap<%.0fmm, shared=%.1fm)",
                             space_info.get(gid_a), space_info.get(gid_b),
                             OPEN_GAP * 1000, shared_len)

    logger.info("Open adjacency: %d additional space pairs connected (no door)", open_hits)
    return dict(adjacency), space_info, space_points


def steiner_routes(
    cost_grid: np.ndarray,
    occupancy: np.ndarray,
    meta,
    pipe_z: float,
    flur_point: np.ndarray,      # site-aligned [x, y, z]
    room_points: list[tuple[str, np.ndarray]],   # [(name, site-aligned [x,y,z])]
    bend_penalty: float = 50.0,
    network_discount: float = 0.02,  # cost of traversing an already-routed voxel
) -> list[tuple[str, list[np.ndarray]]]:
    """
    Route from a Flur to multiple rooms using a growing-network Steiner approach.

    Algorithm:
    1. Sort rooms by straight-line distance from the Flur.
    2. Route Flur → first (nearest) room with normal A*.
    3. For each subsequent room, discount already-routed voxels to nearly zero
       and run multi-source A* seeded from the ENTIRE existing network.
       The branch point emerges naturally where the new path joins the trunk.
    4. After each route, add its voxels to the network at discounted cost.

    Returns list of (room_name, waypoints_world_3d) for each successfully
    routed room.
    """
    from ifcbox.pipeline.router import find_path
    from ifcbox.pipeline.smoother import reduce_waypoints

    modified_cost = cost_grid.copy()
    network_voxels: list[tuple[int, int]] = []

    # Nudge Flur start to passable voxel
    from ifcbox.pipeline.router import _ensure_passable
    flur_vx = _ensure_passable(modified_cost, occupancy,
                                meta.world_to_voxel(flur_point[:2]))
    if flur_vx is None:
        logger.warning("Flur start has no passable voxel")
        return []

    # Sort rooms nearest-first so the trunk grows outward sensibly
    def dist(rpt):
        rv = meta.world_to_voxel(rpt[:2])
        return abs(rv[0]-flur_vx[0]) + abs(rv[1]-flur_vx[1])

    sorted_rooms = sorted(room_points, key=lambda nr: dist(nr[1]))

    results = []
    for room_name, room_point in sorted_rooms:
        room_vx = _ensure_passable(modified_cost, occupancy,
                                    meta.world_to_voxel(room_point[:2]))
        if room_vx is None:
            continue

        # Multi-source seed: the whole existing network + the Flur start
        seeds = network_voxels + [flur_vx] if network_voxels else None

        voxel_path = find_path(
            modified_cost, occupancy,
            flur_vx, room_vx,
            bend_penalty=bend_penalty,
            seeds=seeds,
        )
        if voxel_path is None:
            logger.warning("Steiner: no path to %r", room_name)
            continue

        # Convert to world waypoints
        waypoints = reduce_waypoints(voxel_path, meta, pipe_z)
        results.append((room_name, waypoints))

        # Add this path's voxels to the network at discounted cost
        for vx, vy in voxel_path:
            if not np.isinf(modified_cost[vx, vy]):
                modified_cost[vx, vy] = network_discount
            network_voxels.append((vx, vy))

        logger.info("  Steiner branch → %r: %d waypoints, network now %d voxels",
                    room_name, len(waypoints), len(set(network_voxels)))

    return results


def _nearest_finite(cost_grid, point, max_radius=60):
    """BFS through ALL cells to find the nearest voxel with finite cost."""
    from collections import deque
    nx, ny = cost_grid.shape
    if not np.isinf(cost_grid[point]):
        return point
    visited = {point}
    q = deque([point])
    while q:
        x, y = q.popleft()
        if not np.isinf(cost_grid[x, y]):
            return (x, y)
        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
            nx_, ny_ = x+dx, y+dy
            if (0 <= nx_ < nx and 0 <= ny_ < ny
                    and (nx_, ny_) not in visited
                    and abs(nx_-point[0]) <= max_radius
                    and abs(ny_-point[1]) <= max_radius):
                visited.add((nx_, ny_))
                q.append((nx_, ny_))
    return point  # give up


def _reachable(cost_grid, start_vx, end_vx, max_cells=50_000):
    """
    Return True if end_vx is reachable from start_vx through finite-cost cells.
    Both start and end are nudged to the nearest finite-cost voxel first so
    that a centroid landing inside a wall doesn't silently block everything.
    """
    from collections import deque
    nx, ny = cost_grid.shape

    start_vx = _nearest_finite(cost_grid, start_vx)
    end_vx   = _nearest_finite(cost_grid, end_vx)

    if np.isinf(cost_grid[start_vx]) or np.isinf(cost_grid[end_vx]):
        return False
    if start_vx == end_vx:
        return True

    visited = {start_vx}
    q = deque([start_vx])
    while q and len(visited) < max_cells:
        x, y = q.popleft()
        if (x, y) == end_vx:
            return True
        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
            nx_, ny_ = x+dx, y+dy
            if (0 <= nx_ < nx and 0 <= ny_ < ny
                    and (nx_, ny_) not in visited
                    and not np.isinf(cost_grid[nx_, ny_])):
                visited.add((nx_, ny_))
                q.append((nx_, ny_))
    return False


def find_route_pairs(model, storey, pipe_z, site_xform, cost_grid=None, meta=None):
    """
    For each apartment Flur on the storey, route to every room connected to it
    via a door (direct door adjacency from the IFC).

    Assignment is based on door topology, not Euclidean distance:
    - Build space adjacency graph from IfcDoor positions
    - BFS from each Flur through the door graph
    - Any room reachable from the Flur in 1–2 hops is included

    Excluded from routing as destinations: Treppenraum, Foyer, Balkon,
    Terrasse, exterior spaces, and other Flur spaces.

    Returns list of (flur_name, start_site_3d, room_name, end_site_3d).
    """
    import ifcopenshell.geom
    from collections import defaultdict, deque

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    SKIP_AS_DESTINATION = (
        "Treppenraum", "Treppenhaus", "Foyer", "Balkon", "Terrasse",
        "nicht begehb", "W8.", "8.0.", "8.3.",
    )
    FLUR_PREFIXES = ("Flur",)

    # ── Build adjacency graph + representative points in one pass ────────────
    # space_points uses representative_point() — guaranteed inside the polygon,
    # even for L-shaped or narrow Flur spaces where bounding-box centre hits a wall.
    adjacency, space_info, space_points = build_door_adjacency(model, storey, site_xform)

    # Merge space_points with name info for convenient lookup
    space_centroids = {gid: (space_info[gid], pt)
                       for gid, pt in space_points.items()
                       if gid in space_info}

    flur_gids = {gid for gid, (name, _) in space_centroids.items()
                 if name.startswith(FLUR_PREFIXES)}

    if not flur_gids:
        logger.warning("No Flur spaces found on this storey.")
        return []

    # ── BFS from each Flur through door graph ─────────────────────────────────
    routes = []
    for flur_gid in sorted(flur_gids):
        flur_name, flur_c = space_centroids[flur_gid]
        start_3d = np.array([flur_c[0], flur_c[1], pipe_z])

        # BFS: collect all rooms reachable from this Flur via doors
        # (stop at Treppenraum / communal spaces — don't cross into them)
        visited = {flur_gid}
        queue = deque([flur_gid])
        reachable_rooms = []

        while queue:
            current = queue.popleft()
            for neighbour in adjacency.get(current, []):
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                n_name = space_info.get(neighbour, "")

                # Don't cross into forbidden zones or other Flurs
                if any(n_name.startswith(p) for p in
                       ("Treppenraum", "Treppenhaus", "Foyer") + FLUR_PREFIXES):
                    continue

                # Queue for further traversal (rooms can connect to other rooms)
                queue.append(neighbour)

                # Add as a route destination (excluding unwanted space types)
                if not any(n_name.startswith(p) for p in SKIP_AS_DESTINATION):
                    if neighbour in space_centroids:
                        _, room_c = space_centroids[neighbour]
                        dist = float(np.linalg.norm(flur_c - room_c))
                        reachable_rooms.append((n_name, room_c, dist))

        reachable_count = 0
        skipped_count = 0
        for room_name, room_c, dist in sorted(reachable_rooms, key=lambda r: r[2]):
            end_3d = np.array([room_c[0], room_c[1], pipe_z])

            # Cost-grid connectivity pre-check (filters routing dead-ends)
            if cost_grid is not None and meta is not None:
                sv = meta.world_to_voxel(start_3d[:2])
                ev = meta.world_to_voxel(end_3d[:2])
                if not _reachable(cost_grid, sv, ev):
                    skipped_count += 1
                    continue

            routes.append((flur_name, start_3d, room_name, end_3d))
            logger.info("  → %r (%.1fm)", room_name, dist)
            reachable_count += 1

        logger.info("Flur %r → %d door-connected rooms (%d cost-grid skipped)",
                    flur_name, reachable_count, skipped_count)

    return routes


def run_all_routes(ifc_path, floor_idx, use_strict_doors=True, no_view=False):
    from ifcbox.debug import render_debug_scene
    from ifcbox.engine import RouteParams, build_routing_cost, prepare_floor
    from ifcbox.pipeline.export import export_gltf, export_json
    from ifcbox.pipeline.loader import extract_floor_geometry, list_storeys, load_model
    from ifcbox.pipeline.mesh import build_pipe_mesh
    from ifcbox.pipeline.smoother import path_length

    _strict = use_strict_doors

    class Args:
        ifc = ifc_path
        floor = floor_idx
        resolution = 0.1
        clearance_weight = 10.0   # increased: push routes to corridor centres
        wall_penalty = 500.0
        bend_penalty = 20.0
        strict_doors = _strict
        debug = True

    args = Args()
    t0 = time.time()

    logger.info("Loading IFC...")
    model = load_model(ifc_path)
    storeys = list_storeys(model)
    storey = storeys[floor_idx]
    logger.info("Storey: %s", storey.name)

    logger.info("Extracting floor geometry...")
    floor_geom = extract_floor_geometry(model, storey)
    st = floor_geom.site_transform

    logger.info("Building cost grid (shared across all routes)...")
    prep = prepare_floor(model, storey, floor_index=floor_idx,
                         model_id=Path(ifc_path).stem, resolution=args.resolution,
                         geom=floor_geom)
    params = RouteParams(
        clearance_weight=args.clearance_weight, wall_penalty=args.wall_penalty,
        bend_penalty=args.bend_penalty, strict_doors=args.strict_doors,
    )
    cost_grid = build_routing_cost(prep, params)
    occupancy, wall_costs, meta = prep.occupancy, prep.wall_costs, prep.meta
    corridor, door_zone, forbidden = prep.corridor, prep.door_zone, prep.forbidden

    logger.info("Finding route pairs (Flur → adjacent room)...")
    pairs = find_route_pairs(model, storey, floor_geom.pipe_z, st,
                             cost_grid=cost_grid, meta=meta)
    logger.info("%d route pairs found", len(pairs))

    output_dir = Path("output") / Path(ifc_path).stem
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating wall property debug PNGs...")
    from ifcbox.debug import render_wall_typename_debug, render_wall_properties_debug
    render_wall_typename_debug(model, storey, st, meta,
                               str(output_dir / "debug_wall_typenames.png"))
    render_wall_properties_debug(model, storey, st, meta,
                                 str(output_dir / "debug_wall_properties.png"))

    logger.info("Rendering obstacle debug scene (no route)...")
    render_debug_scene(
        occupancy=occupancy, meta=meta, model=model,
        storey=storey, site_xform=st,
        corridor=corridor, door_zone=door_zone, forbidden=forbidden,
        waypoints=None,
        output_path=str(output_dir / "debug_scene_no_route.png"),
    )

    all_waypoints = []
    all_route_labels = []
    all_pipe_meshes_world = []
    all_waypoints_world = []
    route_idx = 0

    # Group pairs by Flur — one Steiner tree per apartment
    flur_groups: dict[str, tuple[np.ndarray, list]] = {}
    for start_name, start_site, end_name, end_site in pairs:
        if start_name not in flur_groups:
            flur_groups[start_name] = (start_site, [])
        flur_groups[start_name][1].append((end_name, end_site))

    for flur_name, (flur_site, room_list) in flur_groups.items():
        logger.info("Steiner tree: %r → %d rooms", flur_name, len(room_list))

        steiner_results = steiner_routes(
            cost_grid=cost_grid,
            occupancy=occupancy,
            meta=meta,
            pipe_z=floor_geom.pipe_z,
            flur_point=flur_site,
            room_points=room_list,
            bend_penalty=args.bend_penalty,
        )

        for room_name, waypoints in steiner_results:
            route_idx += 1
            length = path_length(waypoints)
            logger.info("  Route %d: → %r  %.2fm, %d waypoints",
                        route_idx, room_name, length, len(waypoints))

            waypoints_world = [st.to_world(wp.reshape(1, 3))[0] for wp in waypoints]
            pipe_mesh = build_pipe_mesh(waypoints, diameter=0.1)
            pipe_mesh_world = st.transform_mesh(pipe_mesh)
            export_json(waypoints_world, output_dir / f"route_{route_idx:02d}.json",
                        storey_name=storey.name)
            export_gltf(pipe_mesh_world, output_dir / f"pipe_{route_idx:02d}.glb")

            all_waypoints.append(waypoints)
            all_pipe_meshes_world.append(pipe_mesh_world)
            all_waypoints_world.extend(waypoints_world)
            flur_short = flur_name.split(":")[0]
            room_short  = room_name.split(":")[0]
            all_route_labels.append(f"{route_idx}: {flur_short} → {room_short}")

    # Combined scene with all routes
    logger.info("Rendering combined debug scene with all routes...")
    _render_combined_scene(
        occupancy, meta, model, storey, st,
        corridor, door_zone, wall_costs, forbidden,
        all_waypoints, all_route_labels,
        str(output_dir / "debug_scene_all_routes.png"),
    )

    logger.info("Done in %.1fs. Outputs in output/", time.time() - t0)

    if not no_view and all_pipe_meshes_world:
        import trimesh
        from ifcbox.visualize import show
        merged_pipe = trimesh.util.concatenate(all_pipe_meshes_world)
        world_meshes = [st.transform_mesh(m) for m in floor_geom.meshes]
        show(
            world_meshes, merged_pipe, all_waypoints_world,
            title=f"IFCBox — {storey.name} — All CHW routes",
        )


def _render_combined_scene(occupancy, meta, model, storey, site_xform,
                            corridor, door_zone, wall_costs, forbidden,
                            all_waypoints, labels, output_path):
    """Render all routes overlaid on a single debug scene."""
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba

    from ifcbox.debug import (
        COLOUR_CORRIDOR, COLOUR_DOOR_ZONE, COLOUR_ENDPOINT,
        COLOUR_EXTERIOR, COLOUR_FORBIDDEN, COLOUR_FREE_ROOM,
        COLOUR_ROUTE, COLOUR_WAYPOINT,
        _draw_door_markers, _draw_nonwall_obstacle_layers,
        _draw_room_labels, _draw_wall_thickness_layer,
    )

    nx, ny = meta.shape
    fig, ax = plt.subplots(figsize=(22, 11))
    ax.set_facecolor(COLOUR_EXTERIOR)

    # Base layer
    free_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
    free = ~occupancy
    r, g, b, _ = to_rgba(COLOUR_FREE_ROOM)
    free_rgba[free.T, :3] = [r, g, b];  free_rgba[free.T, 3] = 1.0
    corr = corridor & free
    cr, cg, cb, _ = to_rgba(COLOUR_CORRIDOR)
    free_rgba[corr.T, :3] = [cr, cg, cb];  free_rgba[corr.T, 3] = 1.0
    ax.imshow(free_rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    _draw_wall_thickness_layer(ax, fig, model, storey, site_xform, meta, nx, ny)
    _draw_nonwall_obstacle_layers(ax, model, meta, storey, site_xform, nx, ny)

    if forbidden is not None and forbidden.any():
        forb_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        fr, fg, fb, _ = to_rgba(COLOUR_FORBIDDEN)
        forb_rgba[forbidden.T, :] = [fr, fg, fb, 0.35]
        ax.imshow(forb_rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    reduced = occupancy & door_zone
    if reduced.any():
        dr_rgba = np.zeros((ny, nx, 4), dtype=np.float32)
        dr, dg, db, _ = to_rgba(COLOUR_DOOR_ZONE)
        dr_rgba[reduced.T, :] = [dr, dg, db, 0.9]
        ax.imshow(dr_rgba, origin="lower", interpolation="nearest", extent=[0, nx, 0, ny])

    _draw_door_markers(ax, model, meta, storey, site_xform)
    _draw_room_labels(ax, model, meta, storey, site_xform)

    route_handles = []
    for i, waypoints in enumerate(all_waypoints):
        vxs = [meta.world_to_voxel(wp[:2])[0] for wp in waypoints]
        vys = [meta.world_to_voxel(wp[:2])[1] for wp in waypoints]
        ax.plot(vxs, vys, color=COLOUR_ROUTE, linewidth=2.0, alpha=0.85, zorder=10)
        for x, y in zip(vxs[1:-1], vys[1:-1]):
            ax.plot(x, y, "o", color=COLOUR_WAYPOINT, markersize=4, zorder=11)
        ax.plot(vxs[-1], vys[-1], "D", color=COLOUR_ENDPOINT, markersize=7, zorder=12)
        ax.plot(vxs[0], vys[0], "s", color=COLOUR_ENDPOINT, markersize=9,
                markeredgecolor="white", zorder=13)

    route_handles = [mpatches.Patch(color=COLOUR_ROUTE, label="CHW route")]

    legend_base = [
        mpatches.Patch(color=COLOUR_CORRIDOR,  label="Corridor / Flur"),
        mpatches.Patch(color=COLOUR_DOOR_ZONE, label="Door crossing zone"),
        mpatches.Patch(color=COLOUR_FORBIDDEN, label="Forbidden zone", alpha=0.5),
    ] + route_handles
    ax.legend(handles=legend_base, loc="upper right", fontsize=7,
              framealpha=0.9, ncol=2)

    title = (f"IFCBox — {storey.name} — All routes  |  "
             f"{'strict doors' if True else 'soft doors'}  |  no Treppenraum")
    ax.set_title(title, fontsize=11)
    ax.set_xlim(0, nx); ax.set_ylim(0, ny)
    ax.set_aspect("equal")
    plt.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved combined debug scene: %s", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IFCBox demo — multi-route Flur test")
    parser.add_argument("ifc", help="Path to IFC file")
    parser.add_argument("--floor", type=int, default=3, help="Storey index (default: 3 = OKFF EG)")
    parser.add_argument("--no-strict-doors", action="store_true",
                        help="Allow crossing any wall (not just door zones)")
    parser.add_argument("--no-view", action="store_true",
                        help="Skip PyVista viewer (export only)")
    args = parser.parse_args()

    run_all_routes(
        ifc_path=args.ifc,
        floor_idx=args.floor,
        use_strict_doors=not args.no_strict_doors,
        no_view=args.no_view,
    )
