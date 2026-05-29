# IFCBox — Phase 2 Spec: Engine Refactor & Backend API

Generated from grilling session 2026-05-29. Decisions are recorded with rationale.

> **Scope:** refactor the Phase 1 proof-of-concept pipeline into a clean, modular **routing engine**, then wrap it in a **FastAPI backend**. This phase is **API-first** — no frontend is built here (see [spec-frontend.md](spec-frontend.md) for the eventual UI, which this API is designed to serve). Pipeline internals are specified in [spec-pipeline.md](spec-pipeline.md). Start at the [plans index](README.md).
>
> **Why API-first:** the current pipeline orchestration is glued into the CLI (`cmd_route(args)` in `route.py`) with `argparse` and `sys.exit`. Before any UI, we want a clean engine with a stable surface that supports the interaction modes the frontend will need: point→point, point→many-points, and room→rooms.

---

## 1. Confirmed Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | First milestone | **API-only** (no frontend yet) | De-risk the engine + service surface before UI work |
| 2 | Engine internal split | **Two-layer**: cached param-independent `PreparedFloor` + cheap per-request `route()` | Expensive mesh/voxel work runs once per floor; routing stays fast |
| 3 | Input model | **Unified anchors** (`point` \| `terminal` \| `room`) + resolver layer; 1 source + N targets | One code path serves all three interaction modes; engine core stays point/voxel-based |
| 4 | Multi-target semantics | **Both modes, default `trunk`** (shared-trunk Steiner) + `independent` | Trunk matches realistic CHW distribution (supply main + branches); `find_path` seeds already do this |
| 5 | Execution model | **Lazy per-floor + background prep**; routing synchronous on a prepared floor | Only prep floors the user touches; routing on cached prep is fast; no Celery for single-user |
| 6 | Repo layout | `ifcbox/` library + sibling `api/` (FastAPI) + future `web/` | Clean lib / app / ui boundaries, minimal churn to existing imports |
| 7 | Serialization | **`.npz` arrays + `meta.json` sidecar** on disk; **SQLite for index/metadata only** | Portable, inspectable, no pickle risk; DB stays small |
| 8 | BIM geometry to client | **Per-floor server-generated `shell.glb`** (glTF), built during prep | Floor-isolated, lightweight; serve glTF not raw IFC (resolves the That-Open-Engine tension — it becomes an optional later upgrade) |
| 9 | Route contract | **Sync result on prepared floor (200); 409 if unprepared** | Prep is the only async thing; routing is a fast sync call |
| 10 | Room → point | **Polygon centroid → nearest passable voxel** | Simple, deterministic, reuses single-target A*; good enough for draft |
| 11 | Doc organization | Domain-named specs + `plans/README.md` index | Ages better than phase-numbered filenames |
| 12 | CLI fate | **`route.py` / `demo_routes.py` become thin engine clients** | CLI becomes the engine's first consumer — validates the API before the HTTP layer; kills duplicated orchestration |

### Baked-in defaults (low-stakes)

- API prefix `/api/v1`.
- Voxel `resolution` is **fixed at 0.1 m** and is a **prep cache key**, not a per-request param (changing it invalidates the whole geometry cache).
- Routing tuning params are **optional per-request overrides** with current CLI defaults: `clearance_weight=5.0`, `wall_penalty=500.0`, `bend_penalty=20.0`, `diameter=0.1`, `corridor_weight=0.25`, `strict_doors=false`.
- **glTF axis convention: Z-up** (matches Revit-exported IFC). `geometry.py`/`export.py` keep trimesh's native Z-up output — no axis flip baked in. If the eventual r3f frontend needs Y-up, it flips client-side.
- Prep progress over **WebSocket**, with `GET floor` status as a **poll fallback**.
- **No auth** (single user).
- **Single-floor only** — vertical risers / multi-floor deferred (Phase 3, see spec-pipeline.md §5).

---

## 2. Engine Refactor (Phase 2a)

The engine is a library (`ifcbox/`) with no web dependencies. The existing `pipeline/*` modules stay as-is (they are already clean); the refactor adds an orchestration layer above them and removes the glue currently living in `route.py`.

### 2.1 New module layout

```
ifcbox/                      # pure engine library (no FastAPI imports)
├── pipeline/                # UNCHANGED low-level modules
│   ├── loader.py            #   (+ add space extraction, see 2.3)
│   ├── voxelizer.py
│   ├── sdf.py
│   ├── router.py            #   find_path (already supports multi-source seeds)
│   ├── smoother.py
│   ├── mesh.py
│   ├── export.py
│   └── zoning.py            #   (refactor: separate masks from magnitudes, see 2.2)
├── engine.py                # NEW: PreparedFloor, prepare_floor(), route()
├── resolver.py              # NEW: Anchor types + resolve_anchor()
├── geometry.py              # NEW: building-shell glTF export
├── debug.py                 # UNCHANGED (debug PNGs become an engine debug option)
└── visualize.py             # UNCHANGED (PyVista, used by CLI)
route.py                     # thin client of engine
demo_routes.py               # thin client of engine (trunk mode)
```

### 2.2 `PreparedFloor` — the cached layer

`PreparedFloor` holds everything that is **param-independent geometry**, built once per `(model, floor, resolution)`.

```python
@dataclass
class PreparedFloor:
    model_id: str
    floor_index: int
    storey: StoreyInfo
    meta: VoxelMeta
    site_transform: SiteTransform
    pipe_z: float

    # arrays (saved to .npz)
    occupancy: np.ndarray        # bool  [nx,ny]
    wall_costs: np.ndarray       # float [nx,ny]  per-voxel wall cost (from mesh types)
    clearance: np.ndarray        # float [nx,ny]  distance_transform_edt
    corridor: np.ndarray         # bool  [nx,ny]  corridor/circulation membership
    door_zone: np.ndarray        # bool  [nx,ny]  wall voxels above door openings
    forbidden: np.ndarray        # bool  [nx,ny]  free voxels that must not be routed

    # metadata (saved to prepared.json)
    terminals: dict              # {ifc_global_id: [x,y,z]}  site-aligned
    spaces: dict                 # {space_id: {name, centroid:[x,y,z], polygon:[[x,y],...]}}
```

> **Refactor note (zoning):** today `build_zone_modifiers` returns float arrays that **bake in cost magnitudes** — `door_wall_cost` is `full(shape, wall_penalty)` with door zones lowered, and `corridor_mask` is a fixed `0.25` multiplier. To make `PreparedFloor` param-independent, change `zoning` to return **boolean membership masks** (`door_zone`, `corridor`) instead. Cost *magnitudes* (`wall_penalty`, door-crossing cost, `corridor_weight`) are applied in `route()` from request params. This is what makes `corridor_weight` a tunable param (decision below).

```python
def prepare_floor(model, storey, resolution: float = 0.1) -> PreparedFloor:
    """Run loader → voxelizer → sdf → zoning (masks only). Param-independent."""

# Persistence
PreparedFloor.save(dir)   # arrays -> prepared.npz (np.savez_compressed),
                          # metadata -> prepared.json
PreparedFloor.load(dir) -> PreparedFloor
```

**Cache key:** `(model_id, floor_index, resolution)`. The on-disk location encodes it (`models/{id}/floors/{n}/`); `resolution` is recorded in `prepared.json` and in the `floor_prep` DB row.

### 2.3 Space extraction (new in loader)

The resolver needs a spaces index (for `room` anchors). Space-reading logic currently lives scattered in `zoning.py` and `demo_routes.py`. Consolidate into `loader.extract_floor_spaces(model, storey, site_xform) -> dict` returning `{space_id: {name, centroid, polygon}}` in site-aligned coords, and fold it into `prepare_floor`.

### 2.4 Anchors & resolver

```python
@dataclass
class PointAnchor:    xyz: tuple[float, float, float]   # world coords
@dataclass
class TerminalAnchor: id: str                            # IfcFlowTerminal GlobalId
@dataclass
class RoomAnchor:     id: str                            # IfcSpace id

Anchor = PointAnchor | TerminalAnchor | RoomAnchor

def resolve_anchor(anchor, prepared: PreparedFloor) -> tuple[int, int]:
    # point    -> force z=pipe_z, to_site, meta.world_to_voxel
    # terminal -> prepared.terminals[id] -> voxel        (404/422 if missing)
    # room     -> prepared.spaces[id].centroid -> voxel  (decision #10)
    #             then nearest-passable snap (router._ensure_passable / _nearest_free)
```

### 2.5 `route()` — the per-request layer

```python
@dataclass
class RouteParams:
    clearance_weight: float = 5.0
    wall_penalty:     float = 500.0
    bend_penalty:     float = 20.0
    diameter:         float = 0.1
    corridor_weight:  float = 0.25   # multiplier on free voxels in corridors (<1 = preferred)
    strict_doors:     bool  = False
    discipline:       str   = "CHW"

@dataclass
class RouteSegment:
    target_id:  str | None      # anchor this branch serves (None for trunk root run)
    waypoints:  list            # [[x,y,z], ...] WORLD coords
    length:     float
    branch_from: int | None     # index into a flattened node list where it branches (trunk mode)

@dataclass
class RouteResult:
    mode: str                   # "trunk" | "independent"
    segments: list[RouteSegment]
    branch_points: list         # [[x,y,z], ...] world coords (trunk mode)
    total_length: float
    diameter: float
    discipline: str
    unreachable_targets: list   # anchor ids A* could not reach

def route(prepared, source: Anchor, targets: list[Anchor],
          mode: str = "trunk", params: RouteParams = RouteParams()) -> RouteResult:
    # 1. cost = build_cost_grid(prepared.clearance, prepared.wall_costs, params.clearance_weight)
    # 2. apply masks with param magnitudes:
    #      cost[corridor & free] *= params.corridor_weight
    #      cost[door_zone] = min(cost, door-crossing cost)   # derived from params.wall_penalty
    #      cost[forbidden & free] = inf
    #    + strict_doors handling (non-door walls -> inf)
    # 3. resolve source + each target to voxels
    # 4. mode == "independent": find_path(src -> t) for each target
    #    mode == "trunk":       find_path(src -> t1); then for each further target
    #                           find_path(seeds = union of existing path voxels -> t)
    #                           (branch point = first seed voxel on the returned path)
    # 5. reduce_waypoints per segment; site_transform.to_world; collect RouteResult
```

The pipe mesh is built on demand from all segment waypoints (`build_pipe_mesh` per segment, merged) and exported to `pipe.glb` — see API §3.

### 2.6 CLI as thin clients

`route.py` and `demo_routes.py` are rewritten to call `prepare_floor` + `route`:

```python
# route.py (sketch)
prep = prepare_floor(model, storey, resolution=args.resolution)
result = route(prep,
               source=_anchor_from_args(args.start, args.start_xyz),
               targets=[_anchor_from_args(args.end, args.end_xyz)],
               mode="trunk",
               params=RouteParams(clearance_weight=args.clearance_weight, ...))
export / visualize / debug PNGs (debug becomes an engine option)
```

Parity check: run the refactored CLI on `model.ifc` and confirm route length / waypoints match the pre-refactor PoC for the same inputs.

---

## 3. Backend API (Phase 2b)

FastAPI app in `api/`, importing the `ifcbox` engine. No engine logic lives here — the API only does HTTP, storage, caching, and background-task orchestration.

### 3.1 Project layout

```
api/
├── main.py            # FastAPI app, /api/v1 router mount, CORS
├── deps.py            # settings, DB session, storage paths
├── store/
│   ├── db.py          # SQLite schema + queries (sqlite3 or SQLModel)
│   └── files.py       # disk layout helpers (paths for models/floors/routes)
├── cache.py           # PreparedFloor load/save + in-process LRU over disk cache
├── tasks.py           # background prep task + WS progress broadcasting
├── schemas.py         # Pydantic request/response models (Anchor, RouteRequest, ...)
└── routers/
    ├── models.py      # upload, list, get, delete
    ├── floors.py      # floor detail, prepare, geometry, prep WS
    └── routes.py      # route submission, history, mesh, delete
```

### 3.2 Storage layout

```
data/
├── ifcbox.db                       # SQLite (index/metadata only)
├── models/{model_id}/
│   ├── original.ifc
│   ├── meta.json                   # storeys[], length_unit_scale, upload time
│   └── floors/{n}/
│       ├── prepared.npz            # occupancy, wall_costs, clearance, corridor_mask,
│       │                           #   door_zone, forbidden
│       ├── prepared.json           # terminals, spaces, site matrix, meta, pipe_z, resolution
│       └── shell.glb               # building-shell glTF (world coords)
└── routes/{route_id}/
    ├── request.json
    ├── route.json                  # serialized RouteResult
    └── pipe.glb
```

### 3.3 SQLite schema (index only)

```sql
CREATE TABLE models (
  id            TEXT PRIMARY KEY,
  filename      TEXT,
  uploaded_at   TEXT,
  storey_count  INTEGER,
  status        TEXT,              -- uploaded | error
  unit_scale    REAL
);
CREATE TABLE floor_prep (
  model_id      TEXT,
  floor_index   INTEGER,
  status        TEXT,              -- unprepared | preparing | ready | error
  resolution    REAL,
  prepared_at   TEXT,
  error         TEXT,
  PRIMARY KEY (model_id, floor_index)
);
CREATE TABLE routes (
  id            TEXT PRIMARY KEY,
  model_id      TEXT,
  floor_index   INTEGER,
  mode          TEXT,
  total_length  REAL,
  segment_count INTEGER,
  created_at    TEXT,
  request_path  TEXT,
  result_path   TEXT,
  mesh_path     TEXT
);
```

### 3.4 REST endpoints (`/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/models` | Upload IFC (multipart). Parses metadata only (storeys). → `{model_id, storeys[], status}` |
| GET | `/models` | List models |
| GET | `/models/{id}` | Model meta + per-floor prep status |
| DELETE | `/models/{id}` | Delete model + all artifacts |
| GET | `/models/{id}/floors/{n}` | Floor detail: prep status, `terminals[]`, `spaces[]` |
| POST | `/models/{id}/floors/{n}/prepare` | Trigger background prep (idempotent). → `202 {status:"preparing"}` |
| GET | `/models/{id}/floors/{n}/geometry` | Building-shell glTF. `200` glb, or `409` if unprepared |
| WS | `/models/{id}/floors/{n}/prepare/ws` | Prep progress stream |
| POST | `/models/{id}/floors/{n}/routes` | Submit route. `200` RouteResult (sync) or `409` if unprepared |
| GET | `/models/{id}/routes` | Route history for a model |
| GET | `/routes/{route_id}` | Route record (RouteResult JSON) |
| GET | `/routes/{route_id}/mesh` | Pipe `pipe.glb` |
| DELETE | `/routes/{route_id}` | Delete a route |

### 3.5 Route request / response

`POST /models/{id}/floors/{n}/routes`

```json
{
  "source": { "type": "room", "id": "<space_id>" },
  "targets": [
    { "type": "terminal", "id": "<global_id>" },
    { "type": "point",    "xyz": [4.84, 47.33, 3.82] },
    { "type": "room",     "id": "<space_id>" }
  ],
  "mode": "trunk",
  "params": { "diameter": 0.1, "clearance_weight": 5.0, "wall_penalty": 500.0,
              "bend_penalty": 20.0, "strict_doors": false }
}
```

Response `200`:

```json
{
  "route_id": "r_abc123",
  "mode": "trunk",
  "total_length": 42.3,
  "diameter": 0.1,
  "discipline": "CHW",
  "segments": [
    { "target_id": "<global_id>", "length": 12.1, "branch_from": 3,
      "waypoints": [[x,y,z], ...] }
  ],
  "branch_points": [[x,y,z], ...],
  "unreachable_targets": [],
  "mesh_url": "/api/v1/routes/r_abc123/mesh"
}
```

### 3.6 Error & status contracts

- `409 Conflict` — floor not prepared (route + geometry endpoints). Body: `{detail, prepare_url}`. Client calls `/prepare`, waits via WS/poll, retries.
- `404` — unknown model / floor / route.
- `422` — anchor references a terminal/space id not on the floor; malformed anchor.
- `200` with non-empty `unreachable_targets` — partial success (some branches found, some not). A* finding *no* path to *any* target with a single point→point request returns `200` with one unreachable target and empty segments (not an error — it's a valid "no route" answer).

### 3.7 WebSocket prep progress

`WS /models/{id}/floors/{n}/prepare/ws` streams JSON frames:

```json
{ "stage": "voxelize", "pct": 40, "message": "rasterizing 312 meshes" }
```

Stages: `extract_meshes → voxelize → clearance → zones → shell_glb → done` (or `{stage:"error", message}`). `GET /models/{id}/floors/{n}` is the poll fallback (returns `floor_prep.status`).

---

## 4. Build Sequencing

### Phase 2a — Engine refactor (library, no web) — done

- [x] **2a-1** `prepare_floor()` + `PreparedFloor` + `save/load`. `zoning` returns boolean `door_zone`/`corridor`/`forbidden`; magnitudes applied at route time. Space extraction in `loader`.
- [x] **2a-2** `resolver.py` (point/terminal/room anchors) + `route()` with `trunk` and `independent` modes + `RouteResult`. `geometry.py` per-element shell glTF + `walls.json` sidecar.
- [x] **2a-3** `route.py` + `demo_routes.py` rewritten as thin engine clients; route length/waypoints match the PoC baseline (4.50 m, identical waypoints).

### Phase 2b — FastAPI backend — done

- [x] **2b-1** App skeleton, SQLite schema, storage helpers. `POST /models` (upload + metadata parse), `GET /models`, `GET /models/{id}`, `DELETE`.
- [x] **2b-2** `POST .../prepare` background task + disk cache + `WS` progress. `GET .../floors/{n}` (status, terminals, spaces, grid). `GET .../geometry`.
- [x] **2b-3** `POST .../routes` (sync, 409 if unprepared) + `RouteResult` serialization + `pipe.glb`. `GET /models/{id}/routes`, `GET /routes/{id}`, `GET /routes/{id}/mesh`.
- [x] **2b-4** Hardening: error contracts, partial-reachability, single-worker prep, endpoint tests on `model.ifc`. **19 tests green.**

### Phase 3 — extensions

- [x] Frontend MVP (see [spec-frontend.md](spec-frontend.md) F-1…F-8) — built.
- [x] Pluggable storage + auth + Docker + Render deploy (see [spec-deploy.md](spec-deploy.md) D-1…D-5; D-6 partial — see hosted-app caveats there).
- [x] Apartment auto-routing demo (`ifcbox/apartments.py` + `GET/POST .../apartments[/refresh]` + front-end "Route apartments" button) — built.

### Testing

- Engine unit tests on `model.ifc` fixtures (prepare_floor determinism, anchor resolution, trunk vs independent).
- CLI parity as an integration smoke test.
- API endpoint tests (upload → prepare → route happy path; 409/404/422 paths).

---

## 5. Open Questions

1. **Multi-goal room targets** — decision #10 routes to a room's centroid. A future refinement is region targeting (reach *any* cell of the room polygon), which needs a multi-goal extension to `find_path`.
2. **Prep concurrency** — Phase 2 serializes prep builds (single worker). Revisit if interactive prep of multiple floors at once is wanted.
3. **glb caching for routes** — `pipe.glb` is written per route; large trunk networks may warrant on-the-fly generation instead of storage. Measure first.

### Resolved (2026-05-29)

- **glTF axis convention** → **Z-up** retained (matches Revit-exported IFC); no flip in export, frontend flips if needed.
- **Corridor weight** → **exposed as `RouteParams.corridor_weight`** (default 0.25); `zoning` returns a boolean `corridor` mask, weight applied in `route()`.

---

## 6. What This Phase Does NOT Include

Deferred — do not let these creep in:

| Feature | Deferred to |
|---|---|
| Any frontend / React UI | Next phase ([spec-frontend.md](spec-frontend.md)) |
| Multi-user auth | Phase 3 |
| Multi-floor / vertical risers | Phase 3 |
| Celery / Redis task queue | Phase 3 |
| PostgreSQL / MinIO | Phase 3 |
| IFC write-back (IfcPipeSegment) | Phase 3 |
| Clash detection, route editing, route variants | Phase 3 |
| In-browser IFC (That Open Engine) | Optional later upgrade — we serve server glTF |
