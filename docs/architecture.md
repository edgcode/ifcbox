# IFCBox — Architecture

Structural reference for the IFCBox routing pipeline. For *what* we are building and phase scope see the [plans index](../plans/README.md) (`plans/spec-pipeline.md`, `plans/spec-api.md`); for *progress and decision history* see `plans/progress.md`. This document describes *how the system is put together*.

_Last reviewed against code: 2026-05-29 (Phase 1 pipeline + Phase 2 engine/API + Phase 3 frontend / deploy / apartments demo)._

---

## 1. System overview

IFCBox takes an IFC building model and one or many points on one storey, and produces a draft pipe route (waypoints + 3D mesh) that avoids building obstacles. The system has three layers — all built:

1. **Engine library** (`ifcbox/`) — pure-Python, no HTTP. The Phase 1 pipeline + a Phase 2 layer (`PreparedFloor` + `route()` + anchors + per-element shell glTF + apartment discovery).
2. **API** (`api/`) — FastAPI wrapper. Thin HTTP/storage/orchestration layer over the engine, with a pluggable storage backend (local FS+SQLite for dev, Cloudflare R2 + Neon Postgres for prod).
3. **Frontend** (`web/`) — React + TypeScript (Vite) + react-three-fiber. Renders the server-generated glTF, authors routes, and ships the apartment auto-routing demo.

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
- `debug.py`: 2D floor-plan PNGs — colour-coded obstacles, corridor/door/forbidden zones, all-routes overlay, wall-type-name map, and **two single-floorplan wall-property renderers** (`render_wall_firerating_debug`, `render_wall_thickness_debug`).

### `engine.py` (Phase 2a) — library surface
- `PreparedFloor`: param-independent cached geometry (occupancy / clearance / boolean zone masks / terminals / spaces / `SiteTransform` / `VoxelMeta` / `pipe_z`). `save()` writes `.npz` + `meta.json`; `load()` rehydrates from a directory.
- `prepare_floor(model, storey, …)`: runs loader → voxelizer → sdf → zoning → returns a `PreparedFloor`.
- `route(prep, source, targets, mode, params)`: builds the cheap cost grid per request (so `clearance_weight` / `wall_penalty` / `bend_penalty` / `corridor_weight` / `strict_doors` / `diameter` are per-request), runs the router, returns a `RouteResult` with one `RouteSegment` per target (`trunk` shares a main; `independent` runs N paths).

### `resolver.py` — anchors
- `PointAnchor(xyz)`, `TerminalAnchor(global_id)`, `RoomAnchor(global_id)`; `resolve_anchor()` turns each into a `(vx, vy)` cell (room → polygon centroid → nearest passable voxel).

### `geometry.py` — per-floor shell glTF
- Exports a **per-element** `shell.glb` (one mesh per IFC element, named by GlobalId) plus a `walls.json` sidecar with per-wall attributes (IFC type, thickness, wall type, fire rating). Drives the front-end wall-colour modes.

### `apartments.py` — apartment discovery (Phase 3 demo)
- `discover_apartments(model, storey, site_xform) → [{flur_id, flur_name, room_ids, room_names}]`.
- Builds an `IfcSpace` polygon set from real (non-convex) `mesh.section(...).discrete` outlines — convex hulls of L-shaped rooms leak into neighbours via the open-plan rule.
- Door-adjacency graph: for each `IfcDoor`, sample 0.35 m either side; record edges between the two spaces it connects, and tag the edge **fire-rated** when the host wall (door → `IfcRelFillsElement` → `IfcOpeningElement` → `IfcRelVoidsElement` → wall) has a `Pset_WallCommon.FireRating`.
- Open-plan adjacency: pairs of polygons within 12 cm + ≥40 cm shared boundary count as door-less openings (never fire-rated; no wall to host a rating).
- Per-Flur BFS through the adjacency graph, skipping fire-rated edges and refusing to traverse through *other* Flurs and forbidden zones (stairwells / shafts). Balconies are visited but not listed as destinations.

---

## 5. CLI entry points

- **`route.py`** — single point-to-point route. `--start`/`--end` (terminal GlobalIds) or `--start-xyz`/`--end-xyz`. Tuning flags: `--floor`, `--resolution`, `--clearance-weight`, `--bend-penalty`, `--wall-penalty`, `--strict-doors`, `--debug`, `--no-view`.
- **`demo_routes.py`** — batch demo over a residential floor: discovers apartment Flur spaces, builds a door-adjacency graph, runs a Steiner-tree route from each Flur to its adjacent rooms. Adjacency/apartment grouping is heuristic (the test model has no explicit apartment data) — for demo only; production grouping will be user-driven in the front end.

Both write to `output/<model-stem>/`.

---

## 6. API layer (`api/`) — FastAPI

Thin HTTP/storage/orchestration over the engine. No engine logic here.

```
api/
├── main.py            # FastAPI app, /api/v1, lifespan init_db, static SPA mount
├── auth.py            # require_token dependency (X-App-Token header, or ?token= for assets/WS)
├── deps.py            # request-scoped deps
├── cache.py           # in-process PreparedFloor LRU over the on-disk cache (R2-backed in cloud mode)
├── tasks.py           # single-worker ThreadPoolExecutor for prep; writes shell.glb, walls.json, rooms.png, apartments.json
├── schemas.py         # Pydantic in/out models
├── routers/
│   ├── models.py      # upload, list, get, delete; storey metadata parse
│   ├── floors.py      # detail, prepare (202) + WS progress, geometry (shell.glb), walls, overlays, apartments (+ refresh)
│   └── routes.py      # submit route (sync 200 / 409), fetch, list, mesh, delete
└── storage/
    ├── base.py        # BlobStore + MetaStore protocols
    ├── local.py       # LocalBlobStore (filesystem) + SqliteMeta
    ├── cloud.py       # R2BlobStore (boto3) + PostgresMeta (psycopg + ConnectionPool with check_connection for Neon autosuspend)
    ├── keys.py        # logical blob keys (model_ifc, floor_prepared, floor_shell, floor_walls, floor_rooms, floor_apartments, …)
    └── factory.py     # picks backend from IFCBOX_STORAGE=local|cloud
```

- **Execution:** prep is lazy and per-floor; one worker thread serialises builds. Progress is written to the `floor_prep` row in the meta store and streamed over a WebSocket; routing is synchronous on a prepared floor, **409** if unprepared.
- **Storage abstraction:** routers and tasks call `blobs.write_text(key, …) / blobs.commit(key) / blobs.read_path(key)` and `meta.set_floor_status(…)` — never the backend directly. Tests pin `IFCBOX_STORAGE=local`, so the 19-test suite is offline.
- **PreparedFloor cache under cloud:** `cache.get_prepared()` checks memory → local cache dir (`IFCBOX_CACHE_DIR`, default `/tmp/ifcbox`) → on miss, `BlobStore.read_dir()` pulls `prepared.npz` from R2 into the cache dir. So routing works on a cold container as long as the prep exists in R2.

---

## 7. Frontend (`web/`) — React + react-three-fiber

Renders server-generated glTF and drives the API. No IFC parsing in the browser.

```
web/src/
├── api/                  # typed API client (fetch + XHR for upload byte-progress); Apartment/Walls types
├── state/                # Zustand stores: auth, viewer, selection, routeBuilder, routeResults, theme
├── viewer/               # r3f: BimShell, Markers, PointMarkers, OverlayPlane, PipeNetwork, Clipping, FloorView, colors
├── ui/                   # Login, ModelsView (with upload loader), ModelView, FloorView header, ViewerControls,
│                         #   RouteBuilderPanel (Route apartments + ↻), Legend, ContextMenu, ThemeToggle
└── app/                  # App shell + TanStack Query providers
```

- **Per-element shell:** `BimShell` loads `shell.glb`; node names are GlobalIds, so wall-colour modes recolour material per element using `walls.json`. Apartments referenced by `RoomAnchor` use the same GlobalIds.
- **Apartment auto-routing demo:** `RouteBuilderPanel` fetches `/apartments`, replaces the systems list with one trunk per apartment via `routeBuilder.loadApartments`, then `submitAll` (one click). A small ↻ next to it calls `POST .../apartments/refresh` to recompute without re-prepping. `submitAll`'s mutation reads `useRouteBuilder.getState().groups` so the freshly-loaded apartments are submitted before React re-renders.
- **Loading UX:** prominent card on the models view during upload (XHR byte progress → indeterminate "Parsing on server" phase); centred spinner card in `FloorView` driven by drei's `useProgress()` plus `floor.isLoading`.

---

## 8. Deployment (Phase 3) — as built

- **Single Docker image, one origin** — multi-stage build (Node→Vite bundle, then Python runtime); FastAPI mounts the built bundle at `/` with an SPA fallback and serves the API at `/api/v1/*`.
- **Render Web Service** from the Dockerfile + `render.yaml`.
- **Cloudflare R2** holds all blobs; **Neon Postgres** holds the meta tables (`models`, `floor_prep`, `routes`).
- **Auth:** `IFCBOX_APP_TOKEN` shared secret enforced by `require_token`; `?token=` query carries it for `useGLTF`/`useTexture` and the WS.
- **Free-tier caveat (2026-05-29):** the hosted app is on Render free (512 MB) and Neon free (autosuspends). The 38 MB test IFC OOM-kills prep at 512 MB; smaller IFCs work. First request after idle is slow because both services cold-start. Standard 2 GB removes the OOM; left as-is for the demo.

See [plans/spec-deploy.md](../plans/spec-deploy.md) for env vars, sequencing, and hosted-app notes.
