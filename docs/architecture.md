# IFCBox — Architecture

Structural reference for the IFCBox routing pipeline. For *what* we are building and phase scope see the [plans index](../plans/README.md) (`plans/spec-pipeline.md`, `plans/spec-api.md`); for *progress and decision history* see `plans/progress.md`. This document describes *how the system is put together*.

_Last reviewed against code: 2026-05-29 (Phase 1 pipeline)._

---

## 1. System overview

IFCBox takes an IFC building model and a pair of points on one storey, and produces a draft pipe route (waypoints + 3D mesh) that avoids building obstacles. Phase 1 is a Python CLI pipeline; Phase 2 wraps it in a FastAPI + React web platform (not yet built).

The pipeline is a linear sequence of pure-ish transforms over a single floor:

```
IFC file
  │
  ▼  loader.py
FloorGeometry  (meshes + terminals in site-aligned coords, pipe_z, SiteTransform)
  │
  ▼  voxelizer.py
occupancy grid [nx,ny] bool  +  VoxelMeta
  │
  ▼  sdf.py
clearance field [nx,ny] float  →  cost grid [nx,ny] float
  │
  ▼  zoning.py
corridor_mask · door_wall_cost · forbidden_mask  →  modified cost grid
  │
  ▼  router.py
voxel path  list[(vx,vy)]   (direction-aware A*)
  │
  ▼  smoother.py
waypoints  list[xyz]  (site-aligned → transformed back to world)
  │
  ├─▶ mesh.py    → trimesh pipe mesh
  └─▶ export.py  → route.json + pipe.glb
                 → visualize.py (PyVista) / debug.py (PNGs)
```

Each stage is a separate module under `ifcbox/pipeline/`, callable in isolation — which is how they are tested (see `plans/spec.md` §3.4 implementation order).

---

## 2. Coordinate systems

Three coordinate frames are in play. Getting these right is the subtlest part of the pipeline.

| Frame | Origin / axes | Where used |
|---|---|---|
| **World** | IFC global coordinates (building may be rotated relative to axes) | IFC geometry as loaded; all exported results |
| **Site-aligned** | Building un-rotated and un-translated so walls align with X/Y axes | All internal analysis (voxelization, routing) |
| **Voxel** | Integer grid indices `(vx, vy)` at 100 mm resolution | Routing |

`SiteTransform` (in `loader.py`) carries the 4×4 site-placement matrix derived from `IfcSite` placement, plus its inverse:

- `to_site(points)` — world → site-aligned (used once, at load, to align geometry to axes for clean voxelization).
- `to_world(points)` — site-aligned → world (used at the end, to convert routed waypoints back for export).

**Z is unchanged** by the 2D site rotation, so `pipe_z` is an absolute world elevation throughout. Voxelization and routing are 2D (XY) at a single `pipe_z`.

`VoxelMeta` (in `voxelizer.py`) bridges site-aligned XY and voxel indices: `world_to_voxel(xy)` (clamped to grid) and `voxel_to_world(vx, vy, z)` (returns voxel centre). Note the name says "world" but inputs are site-aligned XY at this stage.

---

## 3. Key data types

| Type | Module | Fields |
|---|---|---|
| `SiteTransform` | loader | `rotation_deg`, `site_matrix` (world→site), `inv_matrix` (site→world); methods `to_site`, `to_world`, `transform_mesh` |
| `StoreyInfo` | loader | `id`, `name`, `elevation` (m, world), `height` (m) |
| `FloorGeometry` | loader | `storey`, `meshes` (site-aligned trimeshes), `mesh_types` (wall class per mesh), `terminals` ({ifc_id: xyz site-aligned}), `bounds_min/max` (site XY), `pipe_z`, `site_transform` |
| `VoxelMeta` | voxelizer | `origin` (site XY of voxel [0,0] corner), `resolution` (m/voxel), `shape` (nx, ny) |

Grids are plain numpy arrays shaped `[nx, ny]`: `occupancy` (bool), `clearance` (float voxels-to-obstacle), `cost` (float), plus zoning masks `corridor_mask` (float multiplier), `door_wall_cost` (float), `forbidden_mask` (bool).

---

## 4. Module responsibilities

### `loader.py` — IFC → FloorGeometry
- Opens IFC, lists `IfcBuildingStorey`s, computes `SiteTransform`.
- Extracts obstacle meshes for one storey via ifcopenshell `create_shape` (USE_WORLD_COORDS), then transforms them to site-aligned coords.
- Obstacle types: walls, columns, curtain walls, stairs/stair-flights, ramps/ramp-flights — vertical elements only. Slabs/roofs/beams excluded (horizontal / overhead → false obstacles at routing elevation).
- Classifies each wall by min XY extent (thickness proxy): `partition` ≤175 mm, `party` ≤350 mm, `external` >350 mm — drives per-type routing penalty (`WALL_PENALTY_DEFAULTS`).
- Extracts `IfcFlowTerminal` positions; normalises units via `_length_unit_scale` (reads `IfcUnitAssignment` SI prefix). `pipe_z = storey.elevation + 2500 mm` (fixed for Phase 1).

### `voxelizer.py` — meshes → occupancy grid
- Rasterizes each site-aligned mesh that spans `pipe_z` onto a 2D 100 mm bool grid. Primary path: `mesh.section()` at `pipe_z` → fill shapely polygon; fallback: XY bounding-box projection when section fails (handles FacetedBrep tessellation gaps).
- 50 mm dilation so sub-voxel thin walls survive rasterization.
- `_mark_exterior` flood-fills outside the building to close open perimeters.

### `sdf.py` — occupancy → cost grid
- `compute_clearance_field`: `distance_transform_edt(~occupancy)` → distance (in voxels) to nearest obstacle.
- `build_cost_grid`: `cost = 1 + clearance_weight / (clearance + ε)`. Hyperbolic decay — expensive near walls, cheap in open space. `clearance_weight` default 5.0.

### `zoning.py` — preference & restriction masks
- `build_zone_modifiers` returns three arrays driven by `IfcSpace` semantics and door geometry:
  - `corridor_mask` — <1.0 multiplier on free voxels in circulation spaces (corridor/Flur/Korridor names; DE+EN patterns) → routes prefer corridors (0.25×).
  - `door_wall_cost` — reduced wall-crossing cost (30 vs 500 default) only at voxels above door openings → wall penetrations preferred at doors.
  - `forbidden_mask` — free voxels that must never be routed (stairwells, lift shafts).
- `apply_zone_modifiers` folds these into the cost grid: scale free-space cost in corridors; take min(cost, door_wall_cost) at wall voxels.

### `router.py` — cost grid → voxel path
- Direction-aware A*, 4-connected (90° bends only). State is `(vx, vy, direction)`; a 90° turn adds `bend_penalty` (default 20.0 at CLI); 180° U-turns prohibited.
- `seeds` param pre-seeds the priority queue with many voxels at cost 0 → multi-source A* for Steiner-tree routing (used by `demo_routes.py`); branch point is the first seed voxel on the returned path.
- `_ensure_passable` nudges start/end out of obstacle voxels (3-pass: passable BFS → wall-crossing BFS → nearest-free fallback).

### `smoother.py` — voxel path → waypoints
- Collapses collinear runs to minimal bend points. Converts voxel indices → site-aligned world XYZ, then (via `SiteTransform.to_world`) back to true world coords for export. `path_length` for reporting.

### `mesh.py` — waypoints → pipe mesh
- Extrudes a circular cross-section (cylinder segments + sphere caps) along the waypoints into a single trimesh. Default diameter 100 mm.

### `export.py` — outputs
- `export_json` (waypoints + metadata: diameter, discipline) and `export_gltf` (`pipe.glb`).

### `visualize.py` / `debug.py` — inspection
- `visualize.py`: interactive PyVista 3D scene — obstacles semi-transparent grey, pipe solid blue, bend-point spheres, endpoint markers.
- `debug.py`: 2D floor-plan PNGs — colour-coded obstacles, corridor/door/forbidden zones, all routes overlay, wall-type-name map, wall-property panels (FireRating + thickness).

---

## 5. CLI entry points

- **`route.py`** — single point-to-point route. `--start`/`--end` (terminal GlobalIds) or `--start-xyz`/`--end-xyz`. Tuning flags: `--floor`, `--resolution`, `--clearance-weight`, `--bend-penalty`, `--wall-penalty`, `--strict-doors`, `--debug`, `--no-view`.
- **`demo_routes.py`** — batch demo over a residential floor: discovers apartment Flur spaces, builds a door-adjacency graph, runs a Steiner-tree route from each Flur to its adjacent rooms. Adjacency/apartment grouping is heuristic (the test model has no explicit apartment data) — for demo only; production grouping will be user-driven in the front end.

Both write to `output/<model-stem>/`.

---

## 6. Phase boundaries (architectural)

Phase 1 (current as built) is a single-floor, point-to-point, in-process pipeline with no persistence beyond output files, driven by `route.py` / `demo_routes.py` CLIs.

**Phase 2 (planned, see [plans/spec-api.md](../plans/spec-api.md))** refactors the orchestration that currently lives in `route.py`'s `cmd_route` into a library engine, *without changing* the `pipeline/*` modules: a cached, param-independent `PreparedFloor` (occupancy, clearance, zone masks, terminals, spaces) + a cheap per-request `route()`; a unified anchor model (point | terminal | room) resolved to voxels; trunk (shared-main Steiner) vs independent multi-target routing; and a per-floor building-shell glTF export. The CLIs become thin clients of this engine. A FastAPI app in a sibling `api/` directory then wraps the engine (lazy per-floor background prep, synchronous routing, `.npz`+SQLite storage). Phase 3 adds multi-floor risers, corridor-graph/Steiner at scale, OpenVDB, Postgres/MinIO/Celery, and IFC write-back.

Keep new engine code library-shaped (pure functions over explicit data types) so the API stays a thin layer. This section will be revised to *as-built* once the Phase 2 refactor lands.
