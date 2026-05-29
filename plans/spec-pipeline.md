# IFCBox — Phase 1 Spec: Backend IFC Parsing & Routing Pipeline

Generated from grilling session 2026-05-28. Decisions are recorded with rationale.

> **Scope of this document:** the **Phase 1 Python routing pipeline** (IFC → voxel grid → SDF → A* → pipe mesh). This is the spatial-intelligence core. The **web platform** (engine refactor + FastAPI backend) is specified separately in [spec-api.md](spec-api.md); the **frontend** in [spec-frontend.md](spec-frontend.md). Start at the [plans index](README.md).
>
> The Phase 2/3 sections below (§4–5) are the *original outline* of the web work. The backend API is now specified in full in [spec-api.md](spec-api.md), which supersedes §4 where they differ.

---

## 1. Confirmed Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Primary user | MEP engineer | Core routing differentiator targets their workflow |
| Core pain | Manual pipe routing (A→B) | Most universal pain, present on every project |
| Output quality | Draft / starting-point | Ships faster, removes construction-readiness liability |
| Deployment | Standalone web platform | IFC import/export, no Revit API dependency |
| MVP discipline | Chilled water (CHW) | Most common in target verticals, no gravity constraints |
| Phase 1 routing | Point-to-point A* | Steiner tree in Phase 2 |
| Test file | `model.ifc` (38MB, 18 storeys, FacetedBrep, 110 flow terminals) | Real building geometry |
| Build approach | Solo, Python pipeline first | De-risks spatial intelligence before infrastructure |
| MVP scope | Single-floor, P2P, pipe mesh visualisation | Proves spatial intelligence cleanly |
| Voxel resolution | 100mm dense numpy bool | Sufficient for draft routing, OpenVDB deferred to Phase 3 |
| Routing algorithm | SDF-weighted A* | Better path aesthetics than binary occupancy, minimal extra code |
| Path smoothing | Waypoint reduction | Collapses voxel path to clean bend points |
| Phase 1 visualisation | PyVista | Best-in-class engineering mesh renderer |
| Phase 1 outputs | PyVista view + JSON waypoints + glTF mesh | JSON → future API response; glTF → Navisworks/Revit import |
| Build sequencing | Sequential: pipeline → API → viewer | Avoids infrastructure distraction during spatial work |
| Phase 2 storage | Single-user + SQLite + local filesystem | Migrate to PostgreSQL when multi-user is needed |

---

## 2. What We Are NOT Building (Yet)

Explicitly deferred — do not let these creep into Phase 1 or 2:

| Feature | Deferred to |
|---|---|
| Multi-floor routing | Phase 2 |
| Corridor graph extraction | Phase 2 |
| Steiner tree (multi-terminal) | Phase 2 |
| OpenVDB sparse volumetrics | Phase 3 |
| PostgreSQL + PostGIS | Phase 3 |
| Redis + Celery task queue | Phase 3 |
| MinIO / S3 object storage | Phase 3 |
| IFC write-back (IfcPipeSegment) | Phase 3 |
| Multi-user auth | Phase 3 |
| HVAC duct / cable tray routing | Future |
| Hydraulic / pressure analysis | Future |
| Revit plugin / connector | Future |

---

## 3. Phase 1 — Python Pipeline

**Goal:** Run `python route.py model.ifc --floor 5 --start <terminal_id> --end <terminal_id>` and get:
- PyVista window: building obstacles (semi-transparent) + pipe mesh (solid)
- `output/route.json`: waypoints as `[[x, y, z], ...]`
- `output/pipe.glb`: glTF pipe mesh

### 3.1 Module Structure

```
ifcbox/
├── pipeline/
│   ├── loader.py       # IFC loading, storey extraction, mesh extraction, terminal extraction
│   ├── voxelizer.py    # Rasterize obstacle meshes → 100mm occupancy grid (numpy bool)
│   ├── sdf.py          # distance_transform_edt → clearance field (numpy float)
│   ├── router.py       # A* on SDF-weighted cost grid → voxel path
│   ├── smoother.py     # Waypoint reduction → minimal 3D bend points
│   ├── mesh.py         # Extrude circular cross-section → trimesh pipe mesh
│   └── export.py       # JSON waypoints + glTF export
├── visualize.py        # PyVista: building meshes + pipe mesh
├── route.py            # CLI entrypoint
└── requirements.txt
```

### 3.2 Module Specifications

#### `pipeline/loader.py`

```python
load_model(ifc_path: str) -> ifcopenshell.file
list_storeys(model) -> list[dict]  # [{id, name, elevation, height}]
extract_obstacle_meshes(model, storey_id) -> list[trimesh.Trimesh]
    # IFC types: IfcWall, IfcWallStandardCase, IfcColumn, IfcBeam, IfcSlab, IfcCurtainWall
    # Ignore: IfcFurniture, IfcAnnotation, IfcBuildingElementProxy
    # Returns meshes clipped to storey elevation bounds
extract_flow_terminals(model, storey_id) -> dict[str, np.ndarray]
    # Returns {terminal_id: [x, y, z]} for IfcFlowTerminal elements on storey
```

**Key concern:** `model.ifc` uses FacetedBrep geometry. IfcOpenShell's `create_shape()` handles this directly. Use `settings.set(settings.USE_WORLD_COORDS, True)` to get geometry in global coordinates.

#### `pipeline/voxelizer.py`

```python
build_occupancy_grid(
    meshes: list[trimesh.Trimesh],
    floor_bounds: tuple[np.ndarray, np.ndarray],  # (min_xyz, max_xyz)
    resolution: float = 0.1  # metres
) -> tuple[np.ndarray, VoxelMeta]
    # Returns: bool array [nx, ny], metadata (origin, resolution, shape)

@dataclass
class VoxelMeta:
    origin: np.ndarray    # world coords of voxel [0,0]
    resolution: float
    shape: tuple[int, int]

world_to_voxel(point: np.ndarray, meta: VoxelMeta) -> tuple[int, int]
voxel_to_world(vx: int, vy: int, meta: VoxelMeta, z: float) -> np.ndarray
```

**Implementation:** Use `trimesh.voxel.creation.local_voxelize` per mesh, OR rasterize via ray casting. Simpler approach: for each mesh, use trimesh's `bounds` to mark occupied voxels. Most robust: voxelize each mesh with trimesh and OR the grids.

#### `pipeline/sdf.py`

```python
compute_clearance_field(occupancy: np.ndarray) -> np.ndarray
    # scipy.ndimage.distance_transform_edt(~occupancy)
    # Returns float array: distance to nearest obstacle in voxels

build_cost_grid(
    clearance: np.ndarray,
    clearance_weight: float = 2.0
) -> np.ndarray
    # cost = 1.0 + clearance_weight / (clearance + 1e-3)
    # High cost near walls, low cost in open space
```

#### `pipeline/router.py`

```python
find_path(
    cost_grid: np.ndarray,
    occupancy: np.ndarray,
    start_vx: tuple[int, int],
    end_vx: tuple[int, int]
) -> list[tuple[int, int]] | None
    # A* on cost_grid, blocked cells from occupancy
    # Returns voxel coordinate path or None if no path found
```

Use `heapq` for the priority queue. Neighbours: 8-connected (include diagonals). Diagonal move cost: `cost * sqrt(2)`.

**Important:** Add a thin clearance buffer to the occupancy grid before routing (dilate obstacles by `ceil(pipe_radius / resolution)` voxels) so the path centre maintains minimum clearance from walls.

#### `pipeline/smoother.py`

```python
reduce_waypoints(
    voxel_path: list[tuple[int, int]],
    meta: VoxelMeta,
    z: float  # routing elevation on this floor
) -> list[np.ndarray]
    # Collapse collinear segments → minimal bend points in world coords
    # Result: [start_point, bend1, bend2, ..., end_point]
```

**Algorithm:** Walk the path; when direction changes, emit a waypoint. Collinear consecutive points are dropped.

#### `pipeline/mesh.py`

```python
build_pipe_mesh(
    waypoints: list[np.ndarray],
    diameter: float = 0.1  # metres, default 100mm CHW pipe
) -> trimesh.Trimesh
    # Extrude circular cross-section (12-sided polygon) along each segment
    # Add hemispherical caps at endpoints
    # Return single merged trimesh
```

#### `pipeline/export.py`

```python
export_json(waypoints: list[np.ndarray], path: str) -> None
    # {"waypoints": [[x,y,z], ...], "diameter": 0.1, "discipline": "CHW"}

export_gltf(mesh: trimesh.Trimesh, path: str) -> None
    # trimesh.exchange.export.export_mesh(mesh, path, file_type='glb')
```

#### `visualize.py`

```python
show(
    obstacle_meshes: list[trimesh.Trimesh],
    pipe_mesh: trimesh.Trimesh,
    waypoints: list[np.ndarray]
) -> None
    # PyVista plotter
    # Obstacles: opacity=0.3, colour='lightgrey'
    # Pipe mesh: opacity=1.0, colour='#0077CC' (CHW blue)
    # Waypoints: rendered as spheres at bend points
```

#### `route.py` — CLI entrypoint

```python
# Usage:
#   python route.py model.ifc --floor 0 --start <id> --end <id> [--diameter 0.1]
#   python route.py model.ifc --list-floors
#   python route.py model.ifc --floor 0 --list-terminals
```

### 3.3 Dependencies

```
ifcopenshell>=0.7
trimesh[easy]>=4.0
numpy>=1.24
scipy>=1.10
pyvista>=0.42
networkx>=3.0        # for future use, include now
scikit-image>=0.21   # for future corridor graph
```

Install IfcOpenShell via conda (`conda install -c conda-forge ifcopenshell`) or the wheel from the IfcOpenShell releases page. Not on PyPI directly.

### 3.4 Implementation Order

Build and test each module in isolation before wiring the CLI:

1. `loader.py` → confirm storeys and terminals extract correctly from `model.ifc`
2. `voxelizer.py` → dump occupancy grid to matplotlib PNG, verify walls are visible
3. `sdf.py` → dump clearance field as heatmap, verify distance falloff looks correct
4. `router.py` → route between two hardcoded voxel coordinates, print path length
5. `smoother.py` → verify waypoint count is minimal (expect 3–10 for a simple run)
6. `mesh.py` → export pipe mesh as OBJ, open in MeshLab/Blender to verify geometry
7. `export.py` → verify JSON and glTF write correctly
8. `visualize.py` → wire all outputs together in PyVista
9. `route.py` → wire CLI with argparse

### 3.5 Known Risks

| Risk | Mitigation |
|---|---|
| IfcOpenShell fails to tessellate some FacetedBrep elements | Wrap `create_shape()` in try/except, skip failed elements, log warnings |
| Storey elevation bounds are incorrect in IFC | Fall back to computing bounds from mesh extents of floor slab |
| Flow terminal positions are at equipment centre, not pipe connection point | Use terminal bounding box centroid at routing elevation, not raw placement |
| A* finds no path (terminals in separate rooms with no opening) | Return `None` with clear error message; user must pick accessible endpoints |
| Voxelization misses thin walls (< 100mm) | Dilate obstacle meshes by 50mm before rasterizing |

---

## 4. Phase 2 — Web Platform

> **Superseded:** this section is the original sketch. The detailed, current plan for the engine refactor + FastAPI backend is [spec-api.md](spec-api.md). Where the two differ, spec-api.md wins.

**Prerequisite:** Phase 1 Python pipeline is working and tested on `model.ifc`.

**Goal:** Browser interface where an engineer uploads an IFC, picks two terminals on a floor plan, and receives a routed pipe visualised in 3D.

### 4.1 Stack

| Layer | Technology | Notes |
|---|---|---|
| API | FastAPI | Async endpoints, WebSocket progress |
| Pipeline | Phase 1 modules (unchanged) | Imported directly as Python library |
| Storage | SQLite + local filesystem | Single user, no auth |
| Task execution | `asyncio` + `BackgroundTasks` | No Celery for Phase 2 |
| Frontend framework | React + TypeScript | |
| 3D viewer | react-three-fiber + drei | |
| BIM viewer | That Open Engine (openbim-components) | IFC loading in browser |
| State | Zustand | |
| UI | TailwindCSS + shadcn/ui | |
| Networking | TanStack Query + WebSockets | |

### 4.2 API Endpoints

```
POST   /api/models                     Upload IFC file → model_id
GET    /api/models/{id}/floors         List storeys
GET    /api/models/{id}/floors/{n}/terminals   List flow terminals on floor
POST   /api/routes                     Submit routing job → job_id
GET    /api/routes/{id}                Poll route result
GET    /api/routes/{id}/mesh           Download glTF pipe mesh
WS     /ws/routes/{id}                 Stream progress updates
```

### 4.3 POST /api/routes Payload

```json
{
  "model_id": "abc123",
  "floor_index": 5,
  "start_terminal_id": "2O2Fr...",
  "end_terminal_id": "3xYgt...",
  "diameter": 0.1,
  "discipline": "CHW"
}
```

### 4.4 Storage Structure

```
data/
├── models/
│   └── {model_id}/
│       ├── original.ifc
│       ├── meta.json          # storey list, terminal index
│       └── floors/
│           └── {n}/
│               ├── occupancy.npy
│               ├── clearance.npy
│               └── terminals.json
└── routes/
    └── {route_id}/
        ├── waypoints.json
        └── pipe.glb
```

Precompute occupancy and clearance grids at upload time (background task). Cache to disk. Routing requests load cached grids — no recomputation per request.

### 4.5 Frontend Views

1. **Upload page** — drag-and-drop IFC, progress bar during preprocessing
2. **Floor selector** — list of storeys with element counts
3. **Floor plan view** — 2D occupancy overlay with terminal markers, click to select start/end
4. **Route result view** — react-three-fiber 3D viewer, building geometry + pipe mesh, clearance heatmap toggle
5. **Route list** — history of routes for current model, download glTF

### 4.6 Geometry for the Browser

Do NOT stream raw IFC to the browser. Pipeline:

```
IFC upload
    → IfcOpenShell extracts meshes server-side
    → Convert to glTF (trimesh export)
    → Serve glTF to React viewer
```

The BIM viewer (That Open Engine) handles IFC-native loading if needed, but for the floor plan overlay, use the server-generated occupancy grid as a canvas overlay.

---

## 5. Phase 3 — Scale-Out

**Prerequisite:** Phase 2 web platform is working and being used by at least one real engineer.

**Trigger:** Any of these conditions:
- Second user needs access
- Model files exceed 500MB
- Routing jobs exceed 30 seconds
- Multi-floor routing is needed

### 5.1 Infrastructure Upgrades

| Component | Upgrade | Reason |
|---|---|---|
| SQLite → PostgreSQL + PostGIS | Multi-user, spatial indexing, concurrent writes | Second user |
| Local filesystem → MinIO | Large IFC storage, shared access | Large files |
| `BackgroundTasks` → Celery + Redis | Long-running jobs, retries, worker scaling | Slow jobs |
| No auth → JWT (FastAPI Users) | User isolation | Second user |

### 5.2 Spatial Upgrades

| Feature | Implementation |
|---|---|
| Multi-floor routing | Graph nodes as `(floor, x, y)`, riser detection from IfcOpeningElement |
| Corridor graph | Medial axis from clearance field via `skimage.morphology.skeletonize` |
| Steiner tree | NetworkX approximate Steiner tree on corridor graph |
| Sparse volumetrics | OpenVDB via PyVDB for buildings > 100k m² floor area |
| IFC write-back | IfcOpenShell `IfcPipeSegment` + `IfcPipeFitting` creation |

---

## 6. Execution Plan

### Phase 1 Tasks (Python Pipeline)

#### Sprint 1 — IFC Loading & Voxelization (est. 3–5 days)
- [ ] Set up repo structure (`ifcbox/pipeline/`, `requirements.txt`, `README`)
- [ ] `loader.py`: load `model.ifc`, list 18 storeys, extract obstacle meshes for one floor
- [ ] Verify mesh extraction: save floor meshes as OBJ, visually inspect in MeshLab
- [ ] `loader.py`: extract 110 flow terminals, log positions per storey
- [ ] `voxelizer.py`: rasterize one floor to 100mm occupancy grid
- [ ] Debug voxelizer: export grid as matplotlib PNG, confirm walls match IFC geometry

#### Sprint 2 — SDF & Routing (est. 2–3 days)
- [ ] `sdf.py`: compute clearance field, export as heatmap PNG
- [ ] `router.py`: A* between two hardcoded terminal positions on same floor
- [ ] Verify path: plot path over occupancy grid, confirm it avoids obstacles
- [ ] `smoother.py`: reduce to waypoints, print count and coordinates

#### Sprint 3 — Mesh & Visualisation (est. 2–3 days)
- [ ] `mesh.py`: build pipe mesh from waypoints, export as OBJ
- [ ] Inspect pipe mesh in MeshLab: confirm clean geometry, no gaps at bends
- [ ] `export.py`: JSON waypoints + glTF export
- [ ] `visualize.py`: PyVista scene — building (semi-transparent) + pipe (solid blue)
- [ ] `route.py`: wire full CLI with `--list-floors`, `--list-terminals`, `--start`, `--end`

#### Sprint 4 — Hardening (est. 1–2 days)
- [ ] Test with 3 different floor/terminal combinations from `model.ifc`
- [ ] Handle edge cases: no path found, terminal outside voxel grid, failed mesh tessellation
- [ ] Performance check: log time for each pipeline stage, target < 10s total for one floor

### Phase 2 Tasks (Web Platform)

#### Sprint 5 — FastAPI Skeleton (est. 3–4 days)
- [ ] FastAPI project scaffold, SQLite models, file storage structure
- [ ] `POST /api/models` — IFC upload, background preprocessing task
- [ ] `GET /api/models/{id}/floors` and `/terminals`
- [ ] `POST /api/routes` — invoke Phase 1 pipeline, return job_id
- [ ] WebSocket progress endpoint

#### Sprint 6 — React Frontend (est. 5–7 days)
- [ ] Vite + React + TypeScript scaffold, TailwindCSS, shadcn/ui
- [ ] Upload page with preprocessing progress via WebSocket
- [ ] Floor selector and 2D floor plan with terminal markers (canvas overlay)
- [ ] Route submission and polling
- [ ] react-three-fiber 3D viewer: load building glTF + pipe glTF

#### Sprint 7 — Integration & Polish (est. 2–3 days)
- [ ] End-to-end test: upload `model.ifc`, select floor, route two terminals, view result
- [ ] Error states: no path found, preprocessing failure, invalid file
- [ ] glTF download button

### Phase 3 Tasks (Scale-Out)

Defer until triggered by real usage. Document trigger conditions above.

---

## 7. Open Questions (Not Yet Resolved)

These were not grilled — resolve before hitting them in implementation:

1. ~~**Routing elevation within a floor:**~~ **RESOLVED** — pipe runs at `storey_elevation + 2500mm`. Fixed offset, not user-configurable in Phase 1.
2. **Obstacle clearance buffer:** how many mm minimum between pipe outer wall and building obstacles? Suggest `max(150mm, pipe_diameter + 50mm)` as default.
3. **Bend radius constraint:** should waypoint reduction enforce minimum bend radius (e.g. 1.5× pipe diameter)? For a draft tool, straight-line bends are acceptable.
4. **Diagonal routing:** should the router prefer orthogonal-only moves (more realistic for rigid pipe) or allow 45° diagonals (shorter paths)? Suggest orthogonal-only via 4-connected A* for MVP.
5. **Which floor to demo:** with 18 storeys and 110 terminals, which storey has the most interesting routing test? Run `--list-terminals` per floor and pick the one with the most terminals.
