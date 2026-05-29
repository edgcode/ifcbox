# IFCBox — Progress & Decision Log

_Last updated: 2026-05-29 (post-deploy + apartments demo)_

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

## Phase 2 — Engine Refactor & Backend API (DONE 2026-05-29)

Full plan + rationale in [spec-api.md](spec-api.md). Grilled and built in one session.

### Phase 2a — Engine refactor

The PoC orchestration that lived in `route.py`'s `cmd_route` was extracted into a
library engine. The low-level `pipeline/*` modules are unchanged; a two-layer
surface was added on top.

| New / changed | What |
|---|---|
| `ifcbox/engine.py` | `PreparedFloor` (param-independent cached geometry) + `prepare_floor()` + `.npz`/json `save`/`load`; `RouteParams`/`RouteSegment`/`RouteResult`; `route()` (trunk + independent); `build_routing_cost()`; `build_route_mesh()` |
| `ifcbox/resolver.py` | `PointAnchor` / `TerminalAnchor` / `RoomAnchor` + `resolve_anchor()` (room → centroid → nearest passable) |
| `ifcbox/geometry.py` | per-floor building-shell glTF export (Z-up retained, Revit/IFC convention) |
| `pipeline/zoning.py` | `build_zone_masks()` now returns **boolean** `corridor` / `door_zone` / `forbidden`; cost magnitudes applied at route time |
| `pipeline/loader.py` | `extract_floor_spaces()` + `FloorGeometry.spaces` |
| `route.py`, `demo_routes.py` | rewritten as thin engine clients |

**Key decisions (with rationale):**
- **Two-layer split** — `PreparedFloor` holds only param-independent geometry so it
  caches once per `(model, floor, resolution)`; `route()` rebuilds the cheap cost grid
  per request. Lets tuning params change without re-tessellating.
- **Boolean zone masks** — magnitudes (`wall_penalty`, door cost, `corridor_weight`)
  moved out of prep into `route()`. This is what makes `corridor_weight` a tunable
  `RouteParams` field (was a baked-in 0.25).
- **Resolution is a cache key**, not a per-request param (changing it invalidates geometry).
- **Trunk vs independent** — multi-target defaults to `trunk` (shared-main Steiner via
  `find_path` seeds); `independent` runs N separate paths. Trunk ≤ independent length.
- **Cost parity preserved exactly** — `wall_penalty` acts as a ceiling on typed wall
  cost, door zones drop to 30, corridor scales by `corridor_weight`, forbidden = ∞.

### Phase 2b — FastAPI backend (`api/`)

Thin HTTP/storage/orchestration layer over the engine — no engine logic in the API.

- **Layout:** `api/main.py` (app, `/api/v1`, CORS, lifespan `init_db`), `store/db.py`
  (SQLite index), `store/files.py` (disk layout), `cache.py` (PreparedFloor LRU over
  disk), `tasks.py` (background prep), `schemas.py` (Pydantic), `routers/{models,floors,routes}.py`.
- **Storage:** SQLite holds metadata/index only (`models`, `floor_prep`, `routes`);
  arrays as `.npz` + json sidecar on disk; `shell.glb` and `pipe.glb` on disk.
- **Execution:** lazy per-floor prep in a single-worker thread (serialized), progress
  written to the `floor_prep` row; routing is synchronous on a prepared floor, **409**
  if unprepared. Prep progress also streamed over a WebSocket.
- **Endpoints:** model upload/list/get/delete; floor detail (terminals + spaces),
  prepare (202), geometry (per-floor `shell.glb`), prepare-progress WS; route submit
  (sync 200 / 409), history, fetch, mesh, delete. Anchors: point / terminal / room.

### Tests (`tests/`, pytest)

`tests/test_engine.py` + `tests/test_api.py` — **19 tests, green in ~26s**. Cover:
engine route parity vs the pre-refactor baseline (4.50 m, identical waypoints),
`PreparedFloor` save/load roundtrip, trunk ≤ independent + branch points, room-anchor
resolution, unknown-anchor errors, `corridor_weight` tunability; and the full API path
(upload → background prepare → ready → geometry → point + room-trunk routes →
fetch/mesh/history) plus 409 / 422 / 404 contracts and the prepare WS. The test IFC is
gitignored, so tests `skip` cleanly when it is absent.

---

## Phase 3 — Frontend & Deployment

Plans: [spec-frontend.md](spec-frontend.md), [spec-deploy.md](spec-deploy.md).

### Frontend MVP (`web/`) — built 2026-05-29

React + TypeScript (Vite), react-three-fiber + drei, Zustand + TanStack Query,
Tailwind v4. Dev: Vite proxies `/api` → uvicorn. Prod (planned): FastAPI serves the
built bundle (single origin).

| Area | Status |
|---|---|
| Auth gate | token login (localStorage, `X-App-Token`); blank allowed for local dev |
| Models | upload IFC (multipart), list, open, delete |
| Floors | per-floor status; Prepare with live **WebSocket** progress bar |
| 3D viewer | per-floor `shell.glb` (useGLTF), Z-up camera, OrbitControls, one-time Bounds fit |
| Markers | terminals (amber) + room centroids (cyan + name labels), clickable |
| Picking | markers + raycast point-on-shell → point / terminal / room anchors |
| Routing | multi-source **systems** (N independent source→targets, trunk/independent), "Route all" |
| Render | per-system `pipe.glb` in system colour + junction spheres; readout + glb download |
| Overlays (F-7) | occupancy / SDF / **room-type** rasters on a floor-aligned plane + legends; section clip |
| Wall colour modes (F-9) | per-element shading by thickness / wall-type / fire-rating + legend (thickness capped 500 mm, non-walls excluded) |
| Marker UX | point-pick diamonds, **right-click context menu** (set/remove source/target), **3D-picking edit-mode gate** (default off) |
| Theme | light / dark toggle (persisted, default dark); HUD panels stay dark glass in both |

New API added for the frontend: per-floor `geometry` (now per-element shell + `walls.json`),
`overlays/{occupancy,clearance,rooms}`, floor `grid` meta, `/room-classes`.

Key fixes / decisions during the build:
- **Coordinate frame:** the shell glTF and CLI PyVista view must use site→world
  (`SiteTransform.world_mesh`); `transform_mesh` is world→site. Markers and the route
  pipe are true world coords, so the shell rendered detached until fixed.
- **Camera:** only the shell sits inside drei `<Bounds>`, with `observe` OFF — fit once
  on load; clicking a marker no longer refits/flies the camera.
- **Per-element shell:** colour modes need one mesh per IFC element; node names are
  GlobalIds (trimesh may suffix split meshes `_n` → frontend falls back to the stripped id).
- Viewer renders server glTF only (no That Open Engine).

### Frontend — remaining

- **Auth-aware asset loading:** `useGLTF` / `useTexture` don't send `X-App-Token`; wire a
  token-aware loader when auth (D-3) lands.
- Optional: per-system route history (dropped in the F-6b rewrite); viewer code-split
  (three.js makes the bundle ~1.2 MB).

### Deployment — built ([spec-deploy.md](spec-deploy.md) D-1…D-5 done; D-6 partial)

Pluggable storage (Local FS+SQLite ↔ R2+Postgres), shared-secret auth, multi-stage
Dockerfile, single Render web service — all built and deployed.

| Step | Status |
|---|---|
| D-1 storage abstraction (`BlobStore` + `MetaStore`; local/cloud factory) | done |
| D-2 R2 (`boto3`) + Postgres (`psycopg`/pool) + R2-fetch-on-miss in `cache.get_prepared` | done |
| D-3 shared-secret auth (`X-App-Token`; `?token=` for assets/WS) | done |
| D-4 overlay PNG endpoints (occupancy / clearance / rooms) | done as part of Phase 2b |
| D-5 multi-stage Dockerfile + SPA fallback + `render.yaml` | done |
| D-6 deployed to Render + Cloudflare R2 + **Neon** Postgres (smoke) | **partial** — see hosted-app caveats below |

**Hosted app — known limitations (2026-05-29):**
The hosted app is **slow and occasionally unstable** on the free Render
instance (512 MB). The 38 MB test IFC OOM-kills the prep worker during mesh
tessellation; smaller IFCs work. First request after idle is slow because both
Render and Neon spin from cold. Moving to a Render **Standard (2 GB)** tier
fixes the OOM; the free tier is left in place to keep cost at zero for the
demo, with the caveat documented in the user guide. Local mode (Vite + uvicorn
+ FS/SQLite) is the recommended way to actually try it.

**Key decisions (with rationale):**
- **Neon, not Render Postgres** — better free tier + bigger compute window; pay
  the autosuspend cost (see below).
- **Synchronous boto3 + psycopg, single-worker thread for prep** — matches the
  Phase 2b execution model; async R2/PG would force a rewrite of the worker
  with no real concurrency benefit (we only ever prep one floor at a time).
- **`/tmp/ifcbox` local cache for prepared.npz** — Render's FS is ephemeral
  per restart; R2 is the source of truth, the local cache is a hot copy. Fetched
  on miss inside `cache.get_prepared`.
- **Neon `AdminShutdown` after autosuspend** — fixed by giving the
  `psycopg_pool.ConnectionPool` `check=ConnectionPool.check_connection`, which
  pings on checkout and recycles dead connections instead of bubbling the error
  to the request handler.
- **One Docker image, one origin** — FastAPI mounts the built Vite bundle at
  `/` with an SPA fallback; `/api/v1/*` is the API. No prod CORS, one deploy.
- **`pyvista` guarded import** — kept in `requirements.txt` for the CLI but
  imported lazily so the server image doesn't drag in a display stack.

### Polish & misc (this session)
- **Generic-piping framing** — `discipline` defaults to `"generic"` in
  `RouteParams`/`RouteResult`/`export`/`RouteParamsIn`; CLI/demo/viewer strings
  de-CHW'd. The `plans/` specs keep the "CHW" naming as the historical
  decision record. README + `architecture.md` aligned.
- **Wall debug renderers** — `render_wall_properties_debug` (2-panel) split
  into single-floorplan `render_wall_firerating_debug` +
  `render_wall_thickness_debug`; `demo_routes.py` calls both. Same scale as the
  other debug scenes.
- **Theme: light / dark** — system-aware default, persisted, with HUD panels
  retaining a glass look in both modes.

---

## Phase 3 — Apartment auto-routing demo (built 2026-05-29)

Spec: [spec-frontend.md §10](spec-frontend.md). Goal: a one-click demo that
mirrors `demo_routes.py` in the web app — discover each apartment on a floor
and route a trunk from its hallway (Flur) to every room, with each apartment
rendered as its own coloured system.

| Layer | What |
|---|---|
| `ifcbox/apartments.py` | Shared discovery. Door-adjacency graph + door→host-wall→fire-rating tagging + open-plan adjacency rule + per-Flur BFS bounded by fire edges and other Flurs. |
| `tasks.py` | Prep also writes `apartments.json` next to `walls.json`/`rooms.png`. |
| `api/routers/floors.py` | `GET /models/{id}/floors/{n}/apartments` (with lazy backfill if the file is missing on an already-prepared floor); `POST .../apartments/refresh` to recompute against the cached `PreparedFloor` without re-prepping. |
| `web/src/state/routeBuilder.ts` | `loadApartments(apts)` replaces groups with one trunk system per apartment (source = Flur `RoomAnchor`, targets = room `RoomAnchor`s). |
| `web/src/ui/RouteBuilderPanel.tsx` | **"Route apartments (N)"** button + small **↻** refresh button. `submitAll`'s mutation reads groups via `useRouteBuilder.getState().groups` so freshly-loaded apartments are submitted before the next React render. |

**Key decisions (with rationale):**
- **Per-Flur BFS, not connected components** — each Flur is one apartment; the
  BFS treats other Flurs / forbidden zones / fire-rated edges as soft
  boundaries. Connected components would merge two apartments when their
  Wohnen/Küche spaces share an open-plan boundary upstream of a fire door,
  even though the fire door correctly cuts them apart.
- **True (non-convex) section polygons** — initial implementation used
  `MultiPoint(...).convex_hull` (same as `demo_routes.py`); on real L-shaped
  living rooms with balconies the hull bled into the neighbour's hull, which
  the open-plan rule then accepted as a traversable edge and merged the two
  apartments. Switching to `mesh.section(...).discrete` polygons (the actual
  outline of the room footprint) eliminated the cross-apartment leakage. The
  CLI demo will likely benefit from the same fix.
- **Open-plan adjacency rule kept** — door-only adjacency missed rooms
  connected by archways/openings (no `IfcDoor`); the demo's 12 cm gap + 40 cm
  shared-boundary heuristic catches those without crossing partitions.
- **Lazy backfill in the GET endpoint** — floors prepared before the
  apartments feature have no `apartments.json` on disk; rather than force a
  re-prep (mesh re-tessellation, slow), the endpoint computes once on first
  hit, writes the file, and serves it.
- **Explicit refresh button** — a small ↻ next to "Route apartments" calls
  `POST .../apartments/refresh`, which recomputes against the cached
  `PreparedFloor` (no IFC re-parse for `prep`, only `discover_apartments`).
  Lets the user pick up engine-side discovery changes without re-prepping the
  whole floor.

### UI polish (this session)
- **Terminals hidden by default** — `viewer.showTerminals: false`. The
  searchable terminal/room list in the panel also respects the toggle, so the
  list and the scene stay in sync.
- **Storey list cleanup** — dropped the "N terminals · M spaces" chip from
  the ready-floor rows; the list's job is "click to open".
- **Clip top on by default** — `viewer.clip: true`; `FloorView` guards
  rendering on `clip && clipHeight > 0` so the default 0-height plane doesn't
  clip everything off on first paint, before the floor `grid` is loaded.
- **Prominent upload loader** — `api.uploadModel` switched to
  `XMLHttpRequest` for `upload.onprogress` byte events; the models view shows
  a card with filename + determinate bar during transfer, then an
  indeterminate "Parsing on server — up to a minute on the free tier" phase
  once bytes are in.
- **Prominent viewer loader** — `FloorView` overlays a centred spinner card
  using drei's `useProgress()` for r3f asset state plus
  `floor.isLoading` for the floor-detail fetch. Drei's small `<Loader />` bar
  remains as a secondary signal.

### Later — routing quality / scale-out / write-back

- Pipe-chase / riser zone markup; multi-floor risers; clash detection; route variants;
  multi-goal room targeting (reach any cell vs centroid).
- Scale-out: PostGIS, MinIO, Celery/Redis, real multi-user auth (spec-pipeline.md §5).
- IFC write-back: `IfcPipeSegment` / `IfcPipeFitting` into the source IFC (currently glTF + JSON only).

---

## Repository Structure

```
ifcbox/
├── ifcbox/                  # engine library (no web deps)
│   ├── pipeline/
│   │   ├── loader.py        # IFC loading, unit conversion, obstacle + space extraction
│   │   ├── voxelizer.py     # 2D occupancy grid
│   │   ├── sdf.py           # Clearance field + cost grid
│   │   ├── router.py        # A* pathfinder (direction-aware, multi-source seeds)
│   │   ├── smoother.py      # Waypoint reduction
│   │   ├── mesh.py          # Pipe mesh generation
│   │   ├── export.py        # JSON + glTF export
│   │   └── zoning.py        # Boolean corridor / door / forbidden masks
│   ├── engine.py            # PreparedFloor + prepare_floor() + route()
│   ├── resolver.py          # Point/Terminal/Room anchors → voxel
│   ├── geometry.py          # Building-shell glTF export
│   ├── debug.py             # Floor-plan debug PNGs
│   └── visualize.py         # PyVista 3D viewer
├── api/                     # FastAPI backend (imports ifcbox)
│   ├── main.py  deps.py  cache.py  tasks.py  schemas.py
│   ├── store/   (db.py, files.py)
│   └── routers/ (models.py, floors.py, routes.py)
├── web/                     # React + TS frontend (Vite)
│   └── src/ (app/, api/, viewer/, ui/, state/, hooks/)
├── route.py                 # CLI: single route (thin engine client)
├── demo_routes.py           # CLI: batch Steiner demo (thin engine client)
├── tests/                   # pytest: test_engine.py, test_api.py
├── plans/                   # README (index), spec-pipeline, spec-api, spec-frontend, spec-deploy, progress
├── docs/architecture.md     # structural reference
├── data/                    # API runtime store (gitignored)
└── output/<model-stem>/     # CLI per-model output (gitignored)
```
