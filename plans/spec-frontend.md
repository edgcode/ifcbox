# IFCBox — Phase 3 Spec: Frontend

Generated from grilling session 2026-05-29. Decisions recorded with rationale. This supersedes the earlier outline-only version.

> **Scope:** the browser UI that drives the Phase 2b API ([spec-api.md](spec-api.md)). Deployment, storage, and auth are specified in [spec-deploy.md](spec-deploy.md); the engine in [spec-pipeline.md](spec-pipeline.md). Start at the [plans index](README.md).
>
> The frontend is a **high-performance BIM interaction layer** — it renders server-generated glTF, authors routes, and visualises spatial debug data. It does **not** parse IFC, voxelise, or compute SDFs/routes (all server-side).

---

## 1. Confirmed Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | First-build scope | **Fuller MVP**: viewing + click-to-pick + clipping + occupancy/SDF overlays | User wants a capable first build, not just a slice |
| 2 | Endpoint picking | **3D markers + raycast points** | Terminals/rooms as clickable markers (from floor-detail API) + free points via raycast; covers all 3 anchor types, mostly client-side |
| 3 | Viewer stack | **Plain react-three-fiber + drei (GLTFLoader)** | Backend serves glTF → no in-browser IFC parsing; That Open Engine dropped from MVP |
| 4 | Overlays | **Server PNG slices on a plane** | Occupancy + SDF rendered as textures on a floor-aligned plane; lightweight; instanced voxels deferred |
| 5 | Clipping/section | **three.js native clip planes** (client-side) | Floor isolation + section box need no backend |
| 6 | State / data | **Zustand + TanStack Query**; WS for prep progress | Per stack; lightweight viewer state + cached async |

(Deployment-side decisions — single Docker image, one origin, shared-secret auth — live in [spec-deploy.md](spec-deploy.md).)

---

## 2. MVP Feature Set

1. **Auth gate** — one-field token login (stored in `localStorage`, sent as `X-App-Token`).
2. **Model management** — upload IFC (multipart, progress), list/select/delete models.
3. **Floor list + prepare** — per-storey status; trigger prepare; live progress via WebSocket (stages + %).
4. **3D viewer** — load per-floor `shell.glb`; orbit/pan/zoom; floor isolation; clip planes / section box.
5. **Markers** — terminals + room centroids as clickable glyphs (from floor detail); searchable side list mirrors them.
6. **Route builder** — pick source (1) + targets (N) as point (raycast) / terminal / room anchors; choose `trunk`/`independent`; submit; view result.
7. **Route result** — render `pipe.glb`, bend/branch markers, length + per-segment readout; download glb; route history (re-load past routes).
8. **Overlays** — toggle occupancy / SDF (clearance) textured plane at routing elevation.

---

## 3. Stack

| Layer | Choice |
|---|---|
| Framework / lang | React + TypeScript (Vite) |
| 3D | three.js + @react-three/fiber + @react-three/drei |
| State | Zustand |
| Data fetching | TanStack Query |
| Realtime | native WebSocket |
| UI | TailwindCSS + shadcn/ui |
| ~~BIM viewer~~ | ~~That Open Engine~~ — dropped (server serves glTF) |

---

## 4. Architecture

### 4.1 Scene graph (r3f)

```
<Canvas>
  <CameraControls />
  <BimShell url=/floors/{n}/geometry />     # useGLTF(shell.glb) — world coords, Z-up
  <PipeNetwork url=/routes/{id}/mesh />      # pipe.glb (current route)
  <Markers terminals spaces />                # glyphs at world centroids; click -> anchor
  <OverlayPlane kind=occupancy|sdf />         # textured plane at pipe_z (toggle)
  <ClipPlanes />                              # three.js clip planes (section/floor isolate)
  <PickHandler />                             # raycast shell hit -> world xyz -> PointAnchor
</Canvas>
```

> **Coordinate note:** glb is **Z-up** (Revit/IFC convention, [spec-deploy] not flipped server-side). Set the r3f camera/up to Z-up (or apply one root rotation) consistently for shell, pipe, markers, and overlays.

### 4.2 Picking → anchors

- **Raycast** on `BimShell`: hit point (world XYZ) → `{type:"point", xyz}`. Engine forces `z=pipe_z`.
- **Terminal/room glyph** click → `{type:"terminal"|"room", id}`.
- Side panel lists mirror the markers (searchable); selecting a list row = selecting its marker.
- Route builder state: one `source` anchor + ordered `targets[]`; add/remove; `mode` toggle.

### 4.3 Overlays (PNG plane)

The occupancy/SDF grid is axis-aligned in **site** space; the scene is in **world** space. So the textured plane is built in site space then placed via the site→world transform:

- Plane size = `(nx·res) × (ny·res)`, positioned at site `origin`, elevation `pipe_z`.
- Apply `site→world` (Z-rotation + translation) to the plane node so it aligns with the shell.
- Texture = the served PNG (`occupancy.png` / `clearance.png`), `NearestFilter`, toggle opacity.

Requires the API to expose floor **grid meta**: `origin (site x,y)`, `resolution`, `shape (nx,ny)`, `pipe_z`, and the `site→world` transform — added to the floor-detail response (see §6).

### 4.4 Clipping / floor isolation

Pure three.js: `renderer.localClippingEnabled = true` + `Plane`s for a section box; floor isolation is implicit (we only load one floor's shell), with an optional top clip to cut overhead structure.

### 4.5 State (Zustand) & data (TanStack Query)

- **Stores:** `auth` (token), `selection` (current model/floor), `routeBuilder` (source/targets/mode/params), `viewer` (overlay toggle, clip state, camera bookmarks).
- **Queries:** models list, model detail, floor detail (status + terminals + spaces + grid meta), route history, route detail. **Mutations:** upload, prepare, submit route, delete.
- **WS:** subscribe to `…/prepare/ws` while a floor is preparing; drive the progress bar; on `ready`, invalidate the floor query.
- **Auth:** fetch wrapper attaches `X-App-Token`; WS attaches token as query param.

---

## 5. Folder Structure (`web/`)

```
web/
├── src/
│   ├── app/            # routes, layout, providers (Query, theme)
│   ├── api/            # typed client, query/mutation hooks, ws client
│   ├── viewer/         # Canvas, BimShell, PipeNetwork, Markers, OverlayPlane, ClipPlanes, PickHandler
│   ├── routing/        # route builder panel, anchor selection, result readout
│   ├── overlays/       # overlay toggle + plane material
│   ├── ui/             # shadcn components, panels, dialogs, login
│   ├── state/          # zustand stores
│   ├── hooks/          # shared hooks
│   └── types/          # API DTOs (mirror api/schemas.py)
├── index.html  vite.config.ts  tailwind.config.ts  package.json
```

(Dev: Vite proxies `/api` → uvicorn. Prod: built into the Docker image, served by FastAPI — [spec-deploy] §5.)

---

## 6. API additions needed

Most of the MVP rides on the existing Phase 2b endpoints. New work:

| Endpoint | Purpose |
|---|---|
| `GET /models/{id}/floors/{n}/overlays/occupancy.png` | occupancy raster (from PreparedFloor) |
| `GET /models/{id}/floors/{n}/overlays/clearance.png` | SDF heatmap raster |
| extend `GET …/floors/{n}` | add `grid`: `{origin, resolution, shape, pipe_z, site_to_world}` for overlay placement |

Plus the auth dependency + WS token check ([spec-deploy] §7). Picking, markers, routing, geometry, history all use endpoints that already exist.

---

## 7. Build Sequencing

- [x] **F-1** Vite + React + TS scaffold; Tailwind v4; typed API client + Query providers; auth login + token interceptor.
- [x] **F-2** Model upload (XHR byte progress + prominent card) + model list/select/delete.
- [x] **F-3** Floor list + prepare button + WebSocket progress bar.
- [x] **F-4** Viewer: `<Canvas>`, OrbitControls, load `shell.glb` (Z-up), one-time Bounds fit.
- [x] **F-5** Markers (terminals/rooms) + side list; raycast point picking; route-builder state with multi-system support.
- [x] **F-6** Submit route (trunk/independent) → render `pipe.glb` + bend/branch markers + readout; download glb. (Route history dropped from MVP — single active result per system.)
- [x] **F-7** Overlays (occupancy / clearance / rooms PNG plane) + section clip; wall-colour modes (thickness / wall-type / fire-rating) + legend.
- [x] **F-8** Polish: light/dark theme; prominent upload + viewer loaders; clip-top default on; terminals hidden by default; right-click context menu; 3D-picking edit-mode gate.

(Backend prerequisites D-1…D-4 in [spec-deploy.md] all landed alongside F-7/F-8.)

---

## 8. What This Phase Does NOT Include

| Feature | Deferred to |
|---|---|
| Instanced-voxel / shader overlays (vs PNG plane) | Later (if PNG resolution insufficient) |
| In-browser IFC (That Open Engine) | Later (client-side property inspection) |
| Route editing / drag waypoints | Later |
| Multi-floor / riser visualisation | Scale-out (engine doesn't route them yet) |
| Corridor-graph / search-frontier overlays | Later |
| Multi-user, collaboration, comments | Scale-out |
| Mobile layout | Later |

---

## 9. Open Questions

1. **Marker density** — 26 terminals + 44 spaces on one floor is fine; a dense model may need clustering / category filters.
2. **Overlay plane vs depth** — at `pipe_z` the plane may z-fight with overhead structure; may need a small offset or render-order tweak.
3. **Camera up-axis** — confirm Z-up handling end-to-end (shell, pipe, markers, overlay) on first integration; flip once at the root if needed.
4. **Route result vs history** — show only the active route, or overlay multiple past routes? (MVP: active only.)
5. **Large glb streaming** — if a floor shell is heavy, consider draco compression on export.

---

## 10. Built — apartment auto-routing demo (2026-05-29)

A one-click demo that mirrors `demo_routes.py` in the web app: **discover each apartment on a floor and route a trunk from its hallway (Flur) to every room**, with each apartment rendered as its own coloured system. Unlike the CLI demo (which bounds apartments by door topology alone), this version bounds them by **fire-rated walls** — the real apartment/compartment boundary — so the flood-fill can't leak into a neighbour through a shared fire door.

### Why fire-rated walls
Apartment-separating / corridor walls in this model carry a `Pset_WallCommon.FireRating` (e.g. `F90-A`, `BWEW`). The engine already reads per-element `fire_rating` (`FloorGeometry.elements`, served in `walls.json`). Treating a door set in a fire-rated wall as a **non-traversable boundary** turns "rooms reachable from the Flur" into "rooms in the same apartment".

### Backend
- **Extract apartment discovery into the library** — move `build_door_adjacency` + Flur detection + BFS out of `demo_routes.py` into `ifcbox/apartments.py` so the API and CLI share it.
- **Door → host wall → fire rating.** For each `IfcDoor`, resolve its host wall (`IfcRelFillsElement` → `IfcOpeningElement` → `IfcRelVoidsElement` → wall) and read that wall's fire rating. Fallback when the relation is missing: sample the wall voxel(s) under the door against the per-element wall map. Tag each adjacency edge `fire_rated: bool`.
- **Discovery** = build the door-adjacency graph (edges tagged), find Flur spaces, then **BFS from each Flur, skipping fire-rated edges** → `{flur_id, flur_name, room_ids[]}` per apartment.
- **Compute at prepare time** (model + geometry already in hand) and persist `apartments.json` next to `walls.json` / `rooms.png`; serve it:
  `GET /models/{id}/floors/{n}/apartments → [{flur_id, flur_name, room_ids}]`.

### Frontend
- A **"Route apartments"** action in the route panel: fetch `/apartments`, and for each apartment create a routing **system** (`source` = Flur `RoomAnchor`, `targets` = its rooms as `RoomAnchor`s, `mode = trunk`), then **Route all** — one colour per apartment.
- Optional: a "highlight apartments" toggle that tints the room-type overlay by apartment-id instead of room type (reuses the overlay-plane plumbing).

### Sequencing
- [x] **A-1** `ifcbox/apartments.py` (shared discovery) + door→host-wall→fire-rating. Validated on `OKFF OG1` (storey index 2 after raw-deck filter; was 6 before): 4 apartments × {6, 6, 6, 3} rooms, matches the CLI demo.
- [x] **A-2** prepare writes `apartments.json`; `GET …/apartments` endpoint + lazy backfill + `POST …/apartments/refresh`.
- [x] **A-3** front-end "Route apartments (N)" → auto-create systems → Route all; small ↻ refresh button next to it.

### As-built notes (diverges from the plan above)
- **Per-Flur BFS, not connected components.** Each Flur becomes one apartment;
  the BFS treats other Flurs / forbidden zones / fire-rated edges as soft
  boundaries. Components would merge two apartments when their living rooms
  share an open-plan boundary upstream of a fire door, even though the fire
  door correctly cuts them apart.
- **True (non-convex) section polygons.** Used `mesh.section(...).discrete`
  outlines instead of `MultiPoint(...).convex_hull`. Convex hulls of
  L-shaped rooms / balcony-attached living rooms bled into the neighbour's
  hull and the open-plan rule (12 cm gap, ≥40 cm shared boundary) accepted
  them as traversable, merging apartments. Real outlines fixed it.
- **Open-plan adjacency kept.** Door-only adjacency missed Wohnen/Küche ↔
  Flur connections without an `IfcDoor`. Ported the demo's geometric rule and
  marked these edges as *never* fire-rated (there is no wall to host a rating).
- **Lazy backfill in the GET endpoint.** Floors prepared before the feature
  shipped get `apartments.json` written on first request, no re-prep needed.
- **Refresh button (`POST .../apartments/refresh`).** Recomputes against the
  already-cached `PreparedFloor` (the heavy `prepare_floor` doesn't run again).
- **Voxel-sampling fallback** — not implemented yet; the IFC relation path is
  sufficient on the test model.

### Open questions
- **Fire-door detection reliability** — only validated on one test model;
  IFC door↔wall relations vary by exporter. The voxel-sampling fallback
  (or the geometric line-of-sight check) is still worth adding.
- **Flur-less apartments** — apartments with no space named like a corridor need a fallback seed (e.g. the space containing the entrance door, or the largest space).
