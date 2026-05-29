# BIM Pipe Routing Platform — Frontend Specification

# 1. Frontend Objectives

The frontend is responsible for:

* High-performance BIM visualisation
* Interactive route authoring
* Spatial debugging
* Overlay rendering
* User workflows
* Communication with backend routing services

The frontend should NOT:

* perform heavy IFC parsing
* compute voxelisation
* generate SDFs
* run large routing algorithms

Those responsibilities belong to backend services.

---

# 2. Recommended Frontend Stack

| Layer             | Recommendation      |
| ----------------- | ------------------- |
| Framework         | React               |
| Language          | TypeScript          |
| 3D Engine         | react-three-fiber   |
| BIM Viewer        | That Open Engine    |
| Rendering Backend | Three.js            |
| State Management  | Zustand             |
| Data Fetching     | TanStack Query      |
| Styling           | TailwindCSS         |
| UI Components     | shadcn/ui           |
| WebSocket Client  | native ws/socket.io |
| Build Tool        | Vite                |

---

# 3. Core Frontend Architecture

```text
src/
├── app/
├── viewer/
├── overlays/
├── routing/
├── spatial/
├── ui/
├── state/
├── api/
├── hooks/
├── utils/
└── types/
```

---

# 4. Application Layers

# 4.1 Viewer Layer

Responsible for:

* rendering BIM geometry
* camera controls
* clipping planes
* object selection
* visibility filtering

Technologies:

* react-three-fiber
* Three.js
* That Open Engine

---

# 4.2 Routing Layer

Responsible for:

* route authoring
* endpoint selection
* displaying routes
* route previews
* editing paths

---

# 4.3 Spatial Debug Layer

Responsible for visualising:

* voxel occupancy
* SDF heatmaps
* corridor graphs
* graph nodes
* pathfinding expansion
* clash zones

This layer is critical for development/debugging.

---

# 4.4 UI Layer

Responsible for:

* panels
* property inspectors
* filters
* route settings
* toolbars
* dialogs

---

# 4.5 API Layer

Responsible for:

* backend communication
* route requests
* model loading
* websocket updates
* authentication

---

# 5. Recommended Viewer Stack

# Primary Recommendation

## React + react-three-fiber + That Open Engine

Reason:

* BIM-native tooling
* excellent extensibility
* modern React integration
* strong IFC support
* supports custom overlays cleanly

---

# 6. Viewer Responsibilities

The viewer must support:

## Core BIM Features

* IFC model rendering
* large-model streaming
* visibility filters
* floor isolation
* clipping planes
* section boxes
* metadata inspection
* object picking

---

## Spatial Debugging Features

* occupancy voxel rendering
* SDF slice rendering
* corridor graph rendering
* graph node rendering
* route cost visualisation
* search frontier visualisation

---

## Routing Features

* endpoint picking
* route preview
* route editing
* route locking
* rerouting
* clash display

---

# 7. Scene Graph Architecture

Recommended scene organisation:

```text
Scene
├── BIMGeometryLayer
├── RoutingLayer
├── SpatialDebugLayer
├── InteractionLayer
├── TemporaryPreviewLayer
└── UILabelLayer
```

All layers should remain independent.

Avoid tightly coupling:

* BIM rendering
* overlays
* routing logic

---

# 8. BIM Geometry Strategy

# 8.1 DO NOT Render Raw IFC Directly

Preferred workflow:

```text
IFC
 ↓
Backend preprocessing
 ↓
Fragmented glTF/binary geometry
 ↓
Frontend streaming
```

---

# 8.2 Geometry Fragmentation

Geometry should be split into:

* floors
* zones
* fragments
* chunks

Benefits:

* culling
* lazy loading
* visibility control
* scalable rendering

---

# 8.3 Visibility Management

Viewer must support:

* isolate floor
* isolate category
* isolate system
* hide selected
* x-ray mode

---

# 9. React Architecture

# 9.1 State Management

Recommended:

* Zustand

Reason:

* lightweight
* simple
* excellent for viewer state

Store examples:

* selection state
* clipping state
* overlay visibility
* routing state
* active tool
* camera bookmarks

---

# 9.2 Data Fetching

Recommended:

* TanStack Query

Use for:

* model loading
* route polling
* cache management
* async requests

---

# 10. Viewer Components

# 10.1 Main Viewer

```tsx
<ViewerCanvas />
```

Responsibilities:

* initialize renderer
* initialize scene
* camera controls
* render pipeline

---

# 10.2 BIM Geometry Component

```tsx
<BimModel />
```

Responsibilities:

* fragment loading
* geometry rendering
* metadata binding

---

# 10.3 Overlay Components

Examples:

```tsx
<SdfOverlay />
<VoxelOverlay />
<CorridorGraphOverlay />
<RouteOverlay />
```

These should be toggleable independently.

---

# 10.4 Interaction Tools

Examples:

```tsx
<RouteTool />
<SelectTool />
<MeasureTool />
<SectionTool />
```

---

# 11. Recommended Interaction Model

# Selection Workflow

```text
click element
    ↓
retrieve GlobalId
    ↓
query metadata
    ↓
highlight selection
```

---

# Route Authoring Workflow

```text
select start point
    ↓
select endpoint
    ↓
configure route settings
    ↓
submit routing job
    ↓
stream progress
    ↓
display route
```

---

# 12. WebSocket Architecture

Use WebSockets for:

* routing progress
* live updates
* streaming previews
* clash updates

Example:

```text
frontend
    ↕ websocket
backend routing worker
```

---

# 13. Rendering Strategy

# 13.1 Use Instancing

For:

* voxels
* graph nodes
* debug markers

Avoid:

* one mesh per object

---

# 13.2 Use Frustum Culling

Required for:

* large BIM models
* spatial overlays

---

# 13.3 Lazy Loading

Load:

* visible floors
* nearby zones
* requested overlays

Avoid loading entire buildings simultaneously.

---

# 14. Overlay Rendering

# 14.1 Voxel Overlay

Purpose:

* debug occupancy

Representation:

* instanced cubes

---

# 14.2 SDF Overlay

Purpose:

* visualise clearance fields

Representation:

* heatmap slices
* contour planes

---

# 14.3 Corridor Graph Overlay

Purpose:

* visualise routing topology

Representation:

* line segments
* graph nodes

---

# 14.4 Route Overlay

Purpose:

* visualise generated routes

Representation:

* polylines during interaction
* pipe meshes after finalisation

---

# 15. Clipping & Sectioning

The viewer must support:

* clipping planes
* floor slicing
* section boxes
* temporary cutaways

These are essential for MEP workflows.

---

# 16. Recommended Routing UX

# Lightweight During Interaction

While editing:

* render simple polylines

After confirmation:

* generate detailed pipe geometry

Benefits:

* much faster interaction
* lower GPU load

---

# 17. Camera Controls

Recommended features:

* orbit
* fly mode
* orthographic mode
* floor plan mode
* saved viewpoints

---

# 18. Performance Targets

# Desktop

Target:

* 60 FPS interaction
* large federated models

---

# Mobile

Optional future support:

* limited overlays
* reduced detail

---

# 19. Recommended Frontend API Structure

```text
/api/models
/api/routes
/api/overlays
/api/spatial
/ws/routes
```

---

# 20. Suggested Viewer Folder Structure

```text
viewer/
├── components/
├── systems/
├── hooks/
├── overlays/
├── tools/
├── materials/
├── loaders/
├── interactions/
└── rendering/
```

---

# 21. Suggested Overlay Folder Structure

```text
overlays/
├── sdf/
├── voxels/
├── graphs/
├── routes/
├── clashes/
└── measurements/
```

---

# 22. Recommended Viewer Systems

# Rendering System

Responsible for:

* frame loop
* renderer configuration
* postprocessing

---

# Selection System

Responsible for:

* raycasting
* highlighting
* metadata queries

---

# Overlay System

Responsible for:

* debug visualisation
* route overlays
* spatial visualisation

---

# Tool System

Responsible for:

* active interaction tools
* route authoring
* clipping tools

---

# 23. Important Frontend Principles

# DO

* keep frontend lightweight
* stream optimised geometry
* isolate rendering layers
* use backend spatial intelligence
* visualise debugging information

---

# DO NOT

* parse giant IFCs in browser
* build large voxel grids client-side
* compute SDFs client-side
* tightly couple overlays to geometry
* render one mesh per voxel

---

# 24. Recommended MVP Frontend Features

## Phase 1

* IFC model viewing
* selection
* clipping
* route endpoint picking
* route visualisation

---

## Phase 2

* voxel overlays
* SDF overlays
* corridor graphs
* route editing

---

## Phase 3

* real-time rerouting
* clash debugging
* route optimisation visualisation
* multi-user collaboration

---

# 25. Final Recommended Frontend Stack

## Core

* React
* TypeScript
* react-three-fiber
* Three.js

---

## BIM

* That Open Engine

---

## UI

* TailwindCSS
* shadcn/ui

---

## State

* Zustand
* TanStack Query

---

## Communication

* REST API
* WebSockets

---

# 26. Recommended Overall Frontend Philosophy

The frontend should behave as:

```text
a high-performance BIM interaction layer
```

NOT:

* a geometry-processing engine
* a routing computation engine
* a voxel computation engine

Heavy spatial intelligence should remain server-side.

The frontend should prioritise:

* responsiveness
* visual clarity
* interaction quality
* scalable rendering
* modular overlays
* routing UX
