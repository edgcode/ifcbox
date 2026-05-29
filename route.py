#!/usr/bin/env python3
"""
IFCBox — CHW pipe auto-router CLI (thin client over ifcbox.engine).

Usage examples:
  python route.py model.ifc --list-floors
  python route.py model.ifc --floor 6 --list-terminals
  python route.py model.ifc --floor 6 --list-spaces
  python route.py model.ifc --floor 6 --start-xyz 5.3,41.8,6.9 --end-xyz 9.3,42.4,6.9
  python route.py model.ifc --floor 6 --start <global_id> --end <global_id> --debug
  python route.py model.ifc --floor 6 --start-room <space_id> --end-room <space_id>
"""

from __future__ import annotations

import argparse
import json
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
logger = logging.getLogger("ifcbox")


def _get_storey(model, floor: int):
    from ifcbox.pipeline.loader import list_storeys

    storeys = list_storeys(model)
    if floor >= len(storeys):
        logger.error("Floor index %d out of range (0–%d)", floor, len(storeys) - 1)
        sys.exit(1)
    return storeys, storeys[floor]


def cmd_list_floors(args):
    from ifcbox.pipeline.loader import list_storeys, load_model

    storeys = list_storeys(load_model(args.ifc))
    print(f"\n{'#':<4} {'Name':<30} {'Elevation (m)':<16} {'Height (m)'}")
    print("-" * 65)
    for i, s in enumerate(storeys):
        print(f"{i:<4} {s.name:<30} {s.elevation:<16.3f} {s.height:.3f}")
    print(f"\n{len(storeys)} storeys found.\n")


def cmd_list_terminals(args):
    from ifcbox.pipeline.loader import extract_floor_geometry, load_model

    model = load_model(args.ifc)
    _, storey = _get_storey(model, args.floor)
    geom = extract_floor_geometry(model, storey)
    if not geom.terminals:
        print(f"\nNo flow terminals on storey '{storey.name}'.\n")
        return
    print(f"\nTerminals on '{storey.name}' ({len(geom.terminals)} total):\n")
    print(f"{'GlobalId':<26} {'X (m)':>10} {'Y (m)':>10} {'Z (m)':>10}")
    print("-" * 62)
    for gid, pos in sorted(geom.terminals.items()):
        print(f"{gid:<26} {pos[0]:>10.3f} {pos[1]:>10.3f} {pos[2]:>10.3f}")
    print()


def cmd_list_spaces(args):
    from ifcbox.pipeline.loader import extract_floor_geometry, load_model

    model = load_model(args.ifc)
    _, storey = _get_storey(model, args.floor)
    geom = extract_floor_geometry(model, storey)
    if not geom.spaces:
        print(f"\nNo spaces on storey '{storey.name}'.\n")
        return
    print(f"\nSpaces on '{storey.name}' ({len(geom.spaces)} total):\n")
    print(f"{'GlobalId':<26} {'Name':<24} {'X (m)':>9} {'Y (m)':>9}")
    print("-" * 72)
    for gid, s in sorted(geom.spaces.items(), key=lambda kv: kv[1]["name"]):
        c = s["centroid"]
        print(f"{gid:<26} {s['name']:<24} {c[0]:>9.3f} {c[1]:>9.3f}")
    print()


def _anchor(gid, xyz, room, label):
    """Build an Anchor from the start/end CLI args for one endpoint."""
    from ifcbox.resolver import PointAnchor, RoomAnchor, TerminalAnchor

    if xyz:
        coords = [float(v) for v in xyz.split(",")]
        if len(coords) != 3:
            logger.error("%s --xyz must be 'x,y,z'", label)
            sys.exit(1)
        return PointAnchor(tuple(coords))
    if gid:
        return TerminalAnchor(gid)
    if room:
        return RoomAnchor(room)
    logger.error("Provide --%s, --%s-xyz, or --%s-room", label, label, label)
    sys.exit(1)


def cmd_route(args):
    from ifcbox.engine import RouteParams, build_route_mesh, prepare_floor, route
    from ifcbox.pipeline.export import export_gltf
    from ifcbox.pipeline.loader import extract_floor_geometry, load_model

    t0 = time.time()
    model = load_model(args.ifc)
    _, storey = _get_storey(model, args.floor)
    logger.info("Routing on storey '%s' (elevation %.2fm)", storey.name, storey.elevation)

    output_dir = Path("output") / Path(args.ifc).stem
    output_dir.mkdir(parents=True, exist_ok=True)

    geom = extract_floor_geometry(model, storey)
    prep = prepare_floor(model, storey, floor_index=args.floor,
                         model_id=Path(args.ifc).stem, resolution=args.resolution, geom=geom)

    source = _anchor(args.start, args.start_xyz, args.start_room, "start")
    target = _anchor(args.end, args.end_xyz, args.end_room, "end")

    params = RouteParams(
        clearance_weight=args.clearance_weight,
        wall_penalty=args.wall_penalty,
        bend_penalty=args.bend_penalty,
        diameter=args.diameter,
        corridor_weight=args.corridor_weight,
        strict_doors=args.strict_doors,
    )

    result = route(prep, source, [target], mode="trunk", params=params)

    if not result.segments:
        logger.error("No path found (unreachable: %s)", result.unreachable_targets)
        sys.exit(1)

    logger.info("Route length: %.2fm, %d segment(s)",
                result.total_length, len(result.segments))

    pipe_mesh = build_route_mesh(result)
    (output_dir / "route.json").write_text(json.dumps(result.to_dict(), indent=2))
    export_gltf(pipe_mesh, output_dir / "pipe.glb")
    logger.info("Outputs: %s/route.json, %s/pipe.glb", output_dir, output_dir)

    if args.shell:
        from ifcbox.geometry import export_floor_shell
        export_floor_shell(geom.meshes, geom.site_transform, output_dir / "shell.glb")

    if args.debug:
        _render_debug(args, model, storey, prep, geom, result, output_dir)

    logger.info("Pipeline complete in %.1fs", time.time() - t0)

    if not args.no_view:
        from ifcbox.visualize import show
        st = prep.site_transform
        world_meshes = [st.transform_mesh(m) for m in geom.meshes]
        wps = [np.array(w) for w in result.segments[0].waypoints]
        show(world_meshes, pipe_mesh, wps,
             title=f"IFCBox — {storey.name} — CHW route ({result.total_length:.1f}m)")


def _render_debug(args, model, storey, prep, geom, result, output_dir):
    from ifcbox.debug import render_debug_scene
    from ifcbox.pipeline.sdf import build_cost_grid, debug_heatmap
    from ifcbox.pipeline.voxelizer import debug_png

    debug_png(prep.occupancy, str(output_dir / "debug_occupancy.png"))
    debug_heatmap(prep.clearance, prep.occupancy, str(output_dir / "debug_clearance.png"))

    # Site-space waypoints for plotting over the site-aligned voxel grid
    st = prep.site_transform
    site_wps = [st.to_site(np.array(w).reshape(1, 3))[0] for w in result.segments[0].waypoints]

    render_debug_scene(
        occupancy=prep.occupancy, meta=prep.meta, model=model,
        storey=storey, site_xform=st,
        corridor=prep.corridor, door_zone=prep.door_zone, forbidden=prep.forbidden,
        waypoints=site_wps,
        output_path=str(output_dir / "debug_scene.png"),
    )


def main():
    parser = argparse.ArgumentParser(
        description="IFCBox CHW pipe auto-router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("ifc", help="Path to IFC file")

    parser.add_argument("--list-floors", action="store_true", help="List storeys and exit")
    parser.add_argument("--list-terminals", action="store_true", help="List terminals on --floor and exit")
    parser.add_argument("--list-spaces", action="store_true", help="List spaces on --floor and exit")

    parser.add_argument("--floor", type=int, default=0, metavar="N", help="Storey index (default: 0)")
    parser.add_argument("--start", metavar="GLOBAL_ID", help="Start terminal GlobalId")
    parser.add_argument("--end", metavar="GLOBAL_ID", help="End terminal GlobalId")
    parser.add_argument("--start-xyz", metavar="X,Y,Z", help="Start point in world coords")
    parser.add_argument("--end-xyz", metavar="X,Y,Z", help="End point in world coords")
    parser.add_argument("--start-room", metavar="SPACE_ID", help="Start room IfcSpace GlobalId")
    parser.add_argument("--end-room", metavar="SPACE_ID", help="End room IfcSpace GlobalId")

    parser.add_argument("--diameter", type=float, default=0.1, metavar="M", help="Pipe diameter (m, default 0.1)")
    parser.add_argument("--resolution", type=float, default=0.1, metavar="M", help="Voxel resolution (m, default 0.1)")
    parser.add_argument("--clearance-weight", type=float, default=5.0, help="SDF clearance weight (default 5.0)")
    parser.add_argument("--wall-penalty", type=float, default=500.0, help="Wall crossing cost (default 500.0)")
    parser.add_argument("--bend-penalty", type=float, default=20.0, help="Cost per 90° bend (default 20.0)")
    parser.add_argument("--corridor-weight", type=float, default=0.25, help="Corridor cost multiplier (default 0.25)")
    parser.add_argument("--strict-doors", action="store_true", help="Forbid wall crossings except at door zones")
    parser.add_argument("--shell", action="store_true", help="Also export building-shell glTF (shell.glb)")
    parser.add_argument("--no-view", action="store_true", help="Skip PyVista viewer (export only)")
    parser.add_argument("--debug", action="store_true", help="Save debug PNGs to output/")

    args = parser.parse_args()

    if args.list_floors:
        return cmd_list_floors(args)
    if args.list_terminals:
        return cmd_list_terminals(args)
    if args.list_spaces:
        return cmd_list_spaces(args)

    if not (args.start or args.start_xyz or args.start_room):
        parser.print_help()
        print("\nError: provide --start, --start-xyz, or --start-room\n")
        sys.exit(1)
    if not (args.end or args.end_xyz or args.end_room):
        parser.print_help()
        print("\nError: provide --end, --end-xyz, or --end-room\n")
        sys.exit(1)

    cmd_route(args)


if __name__ == "__main__":
    main()
