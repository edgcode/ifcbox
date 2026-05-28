# IFCBox — Progress & Decision Log

_Last updated: 2026-05-28_

---

## What Has Been Built

### Core Pipeline (`ifcbox/pipeline/`)

| Module | What it does |
|---|---|
| `loader.py` | Opens IFC file, lists storeys, extracts obstacle meshes and flow terminal positions in site-aligned coordinates. Detects project length units (mm/m/etc.) and normalises all elevations to metres. Wall elements are classified by thickness into partition / party / external for routing cost assignment. |
| `voxelizer.py` | Rasterises obstacle meshes onto a 2D 100 mm numpy bool grid at the routing elevation. Applies 50 mm dilation to handle sub-voxel thin walls, flood-fills the exterior to close open perimeters, and supports per-mesh wall-crossing costs. |
| `sdf.py` | Runs `scipy.ndimage.distance_transform_edt` on the occupancy grid to produce a clearance field. Builds the A\* cost grid as `1 + clearance_weight / (clearance + ε)` — cells near walls are expensive, open space is cheap. |
| `router.py` | Direction-aware A\* (4-connected, 90° bends only). State is `(vx, vy, direction)`. U-turns forbidden. Bend penalty adds cost per direction change. Supports multi-source seeding for Steiner-tree routing. Endpoint nudging handles terminals that land inside obstacle voxels. |
| `smoother.py` | Collapses collinear voxel runs to minimal bend-point waypoints. Converts voxel indices back to world-space 3D coordinates. |
| `mesh.py` | Extrudes a circular cross-section along waypoints to produce a trimesh pipe mesh (glTF-ready). |
| `export.py` | Writes `route.json` (waypoints + metadata) and `pipe.glb` (glTF mesh). |
| `zoning.py` | Identifies corridor/circulation spaces (by IfcSpace name patterns, DE + EN) and applies a 0.25× cost multiplier to encourage routing through them. Marks stairwells and lift shafts as forbidden zones. Marks wall voxels above door openings with a reduced crossing cost (30 vs 500 default) to allow wall penetrations only at doors. |

### CLI Entry Points

- **`route.py`** — Single point-to-point route. Accepts `--start` / `--end` terminal GlobalIds or `--start-xyz` / `--end-xyz` world coordinates. Flags: `--floor`, `--resolution`, `--clearance-weight`, `--bend-penalty`, `--wall-penalty`, `--strict-doors`, `--debug`, `--no-view`. Outputs land in `output/<model-stem>/`.
- **`demo_routes.py`** — Batch demo for a full residential floor. Discovers apartment Flur spaces, finds adjacent rooms via door-adjacency graph, and runs a Steiner tree route from each Flur to all its adjacent rooms. Outputs to `output/<model-stem>/`.

### Visualisation (`ifcbox/visualize.py`, `ifcbox/debug.py`)

- **PyVista viewer** — Interactive 3D window: building obstacles (semi-transparent grey), pipe mesh (solid blue), bend-point spheres, endpoint markers.
- **Debug PNGs** — Rich 2D floor-plan debug images generated per run:
  - `debug_scene_no_route.png` — all obstacle types colour-coded by IFC class (Wall, Column, StairFlight, etc.), corridor zones, door crossing zones, forbidden zones, room labels.
  - `debug_scene_all_routes.png` — all computed routes overlaid on the floor plan.
  - `debug_wall_typenames.png` — each wall voxel coloured by its `IfcWallType` name (tab20 palette). Used to distinguish construction types — e.g. GK (Gipskarton / drywall) vs KS (Kalksandstein / sandlime brick) vs STB (Stahlbeton / reinforced concrete) — as a proxy for structural criticality and pipe penetration feasibility.
  - `debug_wall_properties.png` — two-panel: left = `Pset_WallCommon.FireRating` (categorical), right = wall thickness from `IfcMaterialLayerSet` (plasma colorbar).

---

## Key Technical Decisions

### Routing

| Decision | Choice | Rationale |
|---|---|---|
| Grid resolution | 100 mm | Sufficient for draft routing; 50 mm doubles memory and compute for marginal gain |
| Routing elevation | `storey.elevation + 2500 mm` | Fixed for Phase 1; above door heads, below slab |
| Cost function | `1 + clearance_weight / (d + ε)` | Hyperbolic decay — cheap to implement, pushes routes to open space |
| `clearance_weight` default | 5.0 (up from 2.0) | 2.0 produced wall-hugging routes on paths shorter than ~8 m |
| `bend_penalty` default | 20.0 (down from 50.0) | 50.0 made 2-bend detours to corridor centres too expensive for short routes |
| Door zone crossing cost | 30.0 (vs 500.0 wall default) | ~6% of wall cost; makes door penetrations strongly preferred without being free |
| Door zone width | `door.OverallWidth / 2` each side | Fixed a 4× oversize bug where `2 * half_width` was passed to a loop that already spans ±steps |

### Obstacle Classification

| Decision | Choice | Rationale |
|---|---|---|
| Obstacle types | IfcWall, IfcWallStandardCase, IfcColumn, IfcCurtainWall, IfcStair, IfcStairFlight, IfcRamp, IfcRampFlight | Vertical elements only |
| IfcSlab / IfcRoof excluded | Intentional | Horizontal elements; a whole-building slab at routing elevation created a 39 × 14 m false obstacle |
| IfcBeam excluded | Intentional (commented out) | Beams at routing elevation are typically overhead structure, not routing barriers |
| Wall cost classification | Thickness → partition / party / external | Proxy for structural weight; used for routing penalty, not displayed in current debug scenes |

### IFC Compatibility

| Issue | Fix |
|---|---|
| Project units (mm vs m) | `_length_unit_scale()` reads `IfcUnitAssignment → IfcSIUnit.Prefix` and returns the conversion factor. Storey elevations multiplied accordingly. Geometry from `create_shape` is always in metres (ifcopenshell auto-converts). |
| FacetedBrep walls with failed `section()` | Strategy 2 in voxelizer: if section fails, fall back to XY bounding-box projection (only if element spans pipe_z) |
| Terminals inside obstacle voxels | BFS nudge in `router.py` — 3-pass: passable BFS → wall-crossing BFS → nearest-free fallback |

### Demo Heuristics (Testing Only)

The demo apartment-grouping logic uses heuristics because `model.ifc` has no explicit apartment assignments:

1. **Flur identification** — IfcSpace names matching `PREFERRED_CORRIDOR_PATTERNS` (flur, korridor, diele, etc.)
2. **Adjacency** — door-sampling: 350 mm either side of each door centroid, check which IfcSpace polygon contains each sample point. Supplemented by geometric proximity (< 120 mm gap) for open-plan connections.
3. **Wall-type grouping** — partition walls (≤ 175 mm) are assumed to be internal apartment walls; party walls (> 175 mm) are assumed to separate apartments. Used as a secondary signal when adjacency is ambiguous.
4. **Fire rating** — `Pset_WallCommon.FireRating` is read by walking `IsDefinedBy` directly (handles null `NominalValue` that `get_psets()` silently skips). Populated values are colour-coded in `debug_wall_properties.png`; walls with no rating show as `"—"`.

These heuristics are for demo/testing. Production grouping will be driven by explicit user selection in the front-end.

---

## Output Structure

```
output/
└── <model-stem>/               # e.g. output/model/ or output/rmebasicsampleproject/
    ├── debug_scene_no_route.png
    ├── debug_scene_all_routes.png
    ├── debug_wall_typenames.png
    ├── debug_wall_properties.png
    ├── route_01.json
    ├── pipe_01.glb
    ├── route_02.json
    ├── pipe_02.glb
    └── ...
```

---

## Phase 2 — Next Steps

### 1. FastAPI Backend

Wrap the pipeline in REST endpoints so the front-end can drive routing without the CLI:

```
POST /api/v1/models                     # upload IFC, returns model_id
GET  /api/v1/models/{id}/storeys        # list storeys
GET  /api/v1/models/{id}/storeys/{n}/terminals   # list flow terminals with positions
GET  /api/v1/models/{id}/storeys/{n}/spaces      # list IfcSpaces with centroids
POST /api/v1/models/{id}/route          # body: {floor, start_xyz, end_xyz, params}
                                        # returns: {waypoints, length, glb_url}
```

Key decisions to make:
- Synchronous (short models) vs async task queue (large models) — likely sync for Phase 2
- Cache occupancy/cost grid per (model_id, floor) to avoid rebuilding on every route request
- SQLite job log: model_id, floor, route params, output paths, timestamp

### 2. React 3D Viewer

Front-end UI for interactive route exploration:

- Load and render `pipe.glb` in Three.js / React Three Fiber
- Display the building shell (from glTF export of obstacle meshes)
- Click-to-pick start/end points on the 3D model
- Show terminal markers; allow selecting from a list
- Route result overlay with waypoint indicators
- Floor switcher

### 3. Routing Quality Improvements

- **Preferred routing zones** — beyond corridor preference, add explicit pipe chase / riser zone markup
- **Multi-floor routing** — vertical risers between storeys (Phase 2 spec already planned)
- **Clash detection** — check proposed route against existing services if present in the IFC
- **Route variants** — return N alternative routes ranked by length / bend count

### 4. IFC Write-back

Export the routed pipe as `IfcPipeSegment` elements back into the source IFC file (Phase 3). Currently only glTF and JSON are written.

---

## Repository Structure

```
ifcbox/
├── ifcbox/
│   ├── pipeline/
│   │   ├── loader.py       # IFC loading, unit conversion, obstacle extraction
│   │   ├── voxelizer.py    # 2D occupancy grid
│   │   ├── sdf.py          # Clearance field + cost grid
│   │   ├── router.py       # A* pathfinder
│   │   ├── smoother.py     # Waypoint reduction
│   │   ├── mesh.py         # Pipe mesh generation
│   │   ├── export.py       # JSON + glTF export
│   │   └── zoning.py       # Corridor preference, door zones, forbidden zones
│   ├── debug.py            # Floor-plan debug PNGs
│   └── visualize.py        # PyVista 3D viewer
├── route.py                # CLI: single point-to-point route
├── demo_routes.py          # CLI: batch demo (Flur → Bad/WC per apartment)
├── plans/
│   ├── spec.md             # Full technical specification
│   └── progress.md         # This file
└── output/
    └── <model-stem>/       # Per-model output folder
```
