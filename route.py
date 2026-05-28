#!/usr/bin/env python3
"""
IFCBox — CHW pipe auto-router CLI.

Usage examples:
  python route.py model.ifc --list-floors
  python route.py model.ifc --floor 0 --list-terminals
  python route.py model.ifc --floor 0 --start <global_id> --end <global_id>
  python route.py model.ifc --floor 0 --start <global_id> --end <global_id> --debug
  python route.py model.ifc --floor 0 --start <global_id> --end <global_id> --no-view
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ifcbox")


def cmd_list_floors(args):
    from ifcbox.pipeline.loader import load_model, list_storeys

    model = load_model(args.ifc)
    storeys = list_storeys(model)
    print(f"\n{'#':<4} {'Name':<30} {'Elevation (m)':<16} {'Height (m)'}")
    print("-" * 65)
    for i, s in enumerate(storeys):
        print(f"{i:<4} {s.name:<30} {s.elevation:<16.3f} {s.height:.3f}")
    print(f"\n{len(storeys)} storeys found.\n")


def cmd_list_terminals(args):
    from ifcbox.pipeline.loader import extract_floor_geometry, list_storeys, load_model

    model = load_model(args.ifc)
    storeys = list_storeys(model)

    if args.floor >= len(storeys):
        logger.error("Floor index %d out of range (0–%d)", args.floor, len(storeys) - 1)
        sys.exit(1)

    storey = storeys[args.floor]
    logger.info("Extracting terminals for storey '%s'...", storey.name)
    floor_geom = extract_floor_geometry(model, storey)

    terminals = floor_geom.terminals
    if not terminals:
        print(f"\nNo flow terminals found on storey '{storey.name}'.\n")
        return

    print(f"\nTerminals on '{storey.name}' ({len(terminals)} total):\n")
    print(f"{'GlobalId':<26} {'X (m)':>10} {'Y (m)':>10} {'Z (m)':>10}")
    print("-" * 62)
    for gid, pos in sorted(terminals.items()):
        print(f"{gid:<26} {pos[0]:>10.3f} {pos[1]:>10.3f} {pos[2]:>10.3f}")
    print()


def _resolve_point(arg_xyz, arg_terminal, label, floor_geom):
    """Return a site-aligned 3D np.ndarray from either --xyz or --terminal args."""
    import numpy as np

    if arg_xyz:
        coords = [float(v) for v in arg_xyz.split(",")]
        if len(coords) != 3:
            logger.error("%s --xyz must be 'x,y,z'", label)
            sys.exit(1)
        # Convert world XYZ → site-aligned
        world = np.array(coords)
        world[2] = floor_geom.pipe_z   # force Z to routing elevation
        return floor_geom.site_transform.to_site(world.reshape(1, 3))[0]
    if arg_terminal:
        if arg_terminal not in floor_geom.terminals:
            logger.error("%s terminal '%s' not found. Use --list-terminals.", label, arg_terminal)
            sys.exit(1)
        return floor_geom.terminals[arg_terminal]
    logger.error("Provide either --start-xyz or --start for %s.", label)
    sys.exit(1)


def build_floor_cost_grid(args, model, floor_geom, output_dir=None):
    """Shared pipeline: occupancy → cost grid → zone modifiers → forbidden mask."""
    import numpy as np

    from ifcbox.pipeline.sdf import build_cost_grid, compute_clearance_field, debug_heatmap
    from ifcbox.pipeline.voxelizer import build_occupancy_grid, debug_png
    from ifcbox.pipeline.zoning import apply_zone_modifiers, build_zone_modifiers

    if output_dir is None:
        output_dir = Path("output")

    logger.info("Building occupancy grid...")
    occupancy, wall_costs, meta = build_occupancy_grid(
        floor_geom.meshes,
        floor_geom.bounds_min,
        floor_geom.bounds_max,
        floor_geom.pipe_z,
        mesh_types=floor_geom.mesh_types,
        resolution=args.resolution,
    )

    logger.info("Computing clearance field...")
    clearance = compute_clearance_field(occupancy)
    cost_grid = build_cost_grid(clearance, occupancy, wall_costs=wall_costs,
                                clearance_weight=args.clearance_weight)

    if args.debug:
        debug_png(occupancy, str(output_dir / "debug_occupancy.png"))
        debug_heatmap(clearance, occupancy, str(output_dir / "debug_clearance.png"))
        from ifcbox.debug import render_wall_typename_debug, render_wall_properties_debug
        render_wall_typename_debug(model, floor_geom.storey, floor_geom.site_transform, meta,
                                   str(output_dir / "debug_wall_typenames.png"))
        render_wall_properties_debug(model, floor_geom.storey, floor_geom.site_transform, meta,
                                     str(output_dir / "debug_wall_properties.png"))

    logger.info("Building zone modifiers...")
    corridor_mask, door_wall_cost, forbidden_mask = build_zone_modifiers(
        model, meta, floor_geom.pipe_z,
        floor_geom.site_transform, occupancy,
        wall_penalty=args.wall_penalty,
    )
    cost_grid = apply_zone_modifiers(cost_grid, occupancy, corridor_mask, door_wall_cost)

    # Apply forbidden zones (Treppenraum etc.) — set free voxels to infinity
    cost_grid[forbidden_mask & ~occupancy] = np.inf

    # Strict door crossing — non-door-zone walls become impassable
    if getattr(args, 'strict_doors', False):
        non_door_walls = occupancy & (door_wall_cost >= args.wall_penalty * 0.9)
        cost_grid[non_door_walls] = np.inf
        logger.info("Strict door mode: %d non-door wall voxels set to ∞", int(non_door_walls.sum()))

    return occupancy, wall_costs, meta, cost_grid, corridor_mask, door_wall_cost, forbidden_mask


def cmd_route(args):
    import numpy as np

    from ifcbox.pipeline.export import export_gltf, export_json
    from ifcbox.pipeline.loader import extract_floor_geometry, list_storeys, load_model
    from ifcbox.pipeline.mesh import build_pipe_mesh
    from ifcbox.pipeline.router import find_path
    from ifcbox.pipeline.smoother import path_length, reduce_waypoints

    t0 = time.time()

    model = load_model(args.ifc)
    storeys = list_storeys(model)
    if args.floor >= len(storeys):
        logger.error("Floor index %d out of range (0–%d)", args.floor, len(storeys) - 1)
        sys.exit(1)
    storey = storeys[args.floor]
    logger.info("Routing on storey '%s' (elevation %.2fm)", storey.name, storey.elevation)

    output_dir = Path("output") / Path(args.ifc).stem
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Extracting floor geometry...")
    floor_geom = extract_floor_geometry(model, storey)

    start_site = _resolve_point(getattr(args, 'start_xyz', None), args.start, "start", floor_geom)
    end_site   = _resolve_point(getattr(args, 'end_xyz', None),   args.end,   "end",   floor_geom)
    logger.info("Start (site): [%.2f, %.2f, %.2f]", *start_site)
    logger.info("End   (site): [%.2f, %.2f, %.2f]", *end_site)

    (occupancy, wall_costs, meta, cost_grid,
     corridor_mask, door_wall_cost, forbidden_mask) = build_floor_cost_grid(
        args, model, floor_geom, output_dir=output_dir)

    if args.debug:
        logger.info("Rendering debug scene...")
        from ifcbox.debug import render_debug_scene
        render_debug_scene(
            occupancy=occupancy, meta=meta, model=model,
            storey=storey, site_xform=floor_geom.site_transform,
            corridor_mask=corridor_mask, door_wall_cost=door_wall_cost,
            forbidden_mask=forbidden_mask,
            waypoints=None,
            output_path=str(output_dir / "debug_scene_no_route.png"),
            wall_penalty=args.wall_penalty,
        )

    start_vx = meta.world_to_voxel(start_site[:2])
    end_vx   = meta.world_to_voxel(end_site[:2])
    logger.info("Voxel coords: start=%s end=%s", start_vx, end_vx)

    logger.info("Running A*...")
    voxel_path = find_path(cost_grid, occupancy, start_vx, end_vx,
                           bend_penalty=args.bend_penalty)

    if voxel_path is None:
        logger.error("No path found.")
        sys.exit(1)

    waypoints = reduce_waypoints(voxel_path, meta, floor_geom.pipe_z)
    length = path_length(waypoints)
    logger.info("Route length: %.2fm, %d waypoints", length, len(waypoints))

    if args.debug:
        from ifcbox.pipeline.voxelizer import debug_png
        from ifcbox.debug import render_debug_scene
        debug_png(occupancy, str(output_dir / "debug_route.png"), waypoints=waypoints, meta=meta)
        render_debug_scene(
            occupancy=occupancy, meta=meta, model=model,
            storey=storey, site_xform=floor_geom.site_transform,
            corridor_mask=corridor_mask, door_wall_cost=door_wall_cost,
            forbidden_mask=forbidden_mask,
            waypoints=waypoints,
            output_path=str(output_dir / "debug_scene.png"),
            wall_penalty=args.wall_penalty,
        )

    logger.info("Building pipe mesh...")
    pipe_mesh = build_pipe_mesh(waypoints, diameter=args.diameter)

    st = floor_geom.site_transform
    waypoints_world = [st.to_world(wp.reshape(1, 3))[0] for wp in waypoints]
    pipe_mesh_world = st.transform_mesh(pipe_mesh)

    export_json(waypoints_world, output_dir / "route.json",
                diameter=args.diameter, discipline="CHW", storey_name=storey.name)
    export_gltf(pipe_mesh_world, output_dir / "pipe.glb")

    elapsed = time.time() - t0
    logger.info("Pipeline complete in %.1fs", elapsed)
    logger.info("Outputs: %s/route.json, %s/pipe.glb", output_dir, output_dir)

    if not args.no_view:
        from ifcbox.visualize import show
        world_meshes = [st.transform_mesh(m) for m in floor_geom.meshes]
        show(world_meshes, pipe_mesh_world, waypoints_world,
             title=f"IFCBox — {storey.name} — CHW route ({length:.1f}m)")


def main():
    parser = argparse.ArgumentParser(
        description="IFCBox CHW pipe auto-router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("ifc", help="Path to IFC file")

    sub = parser.add_subparsers(dest="command")

    # --list-floors (also available as a flag on the main parser for convenience)
    parser.add_argument("--list-floors", action="store_true", help="List storeys and exit")
    parser.add_argument("--list-terminals", action="store_true", help="List terminals on --floor and exit")

    # Routing args
    parser.add_argument("--floor", type=int, default=0, metavar="N", help="Storey index (default: 0)")
    parser.add_argument("--start", metavar="GLOBAL_ID", help="Start terminal GlobalId")
    parser.add_argument("--end",   metavar="GLOBAL_ID", help="End terminal GlobalId")
    parser.add_argument("--start-xyz", metavar="X,Y,Z", help="Start point in world coords (e.g. 4.84,47.33,3.82)")
    parser.add_argument("--end-xyz",   metavar="X,Y,Z", help="End point in world coords (e.g. 3.90,49.76,3.82)")
    parser.add_argument("--diameter", type=float, default=0.1, metavar="M", help="Pipe diameter in metres (default: 0.1)")
    parser.add_argument("--resolution", type=float, default=0.1, metavar="M", help="Voxel resolution in metres (default: 0.1)")
    parser.add_argument("--clearance-weight", type=float, default=5.0, help="SDF clearance weight in cost function (default: 5.0)")
    parser.add_argument("--wall-penalty", type=float, default=500.0, help="Cost for routing through a wall voxel (default: 500.0)")
    parser.add_argument("--bend-penalty", type=float, default=20.0, help="Cost added per 90° bend (default: 20.0, ~2m equivalent)")
    parser.add_argument("--strict-doors", action="store_true", help="Forbid wall crossings except at door zones")
    parser.add_argument("--no-view", action="store_true", help="Skip PyVista viewer (export only)")
    parser.add_argument("--debug", action="store_true", help="Save debug PNGs to output/")

    args = parser.parse_args()

    if args.list_floors:
        cmd_list_floors(args)
        return

    if args.list_terminals:
        cmd_list_terminals(args)
        return

    if not args.start and not args.start_xyz:
        parser.print_help()
        print("\nError: provide --start <terminal_id> or --start-xyz x,y,z\n")
        sys.exit(1)
    if not args.end and not args.end_xyz:
        parser.print_help()
        print("\nError: provide --end <terminal_id> or --end-xyz x,y,z\n")
        sys.exit(1)

    cmd_route(args)


if __name__ == "__main__":
    main()
