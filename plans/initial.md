# BIM Pipe Routing Platform — Technical Specification

## 1. Project Overview

### Objective

Build a web-based BIM spatial intelligence platform capable of:

* Loading and visualising IFC building models
* Generating spatial representations of buildings
* Automatically routing pipework through free space
* Supporting clash-aware routing
* Supporting floor-by-floor scalable routing
* Providing interactive visual editing and debugging tools

The system should support large commercial buildings and scale toward:

* hospitals
* airports
* data centres
* laboratories
* industrial facilities

---

# 2. Core Architectural Principles

## 2.1 Server-Side Spatial Intelligence

All heavy geometry and routing logic should run server-side.

Frontend responsibilities:

* visualisation
* interaction
* user input
* route editing
* overlays

Backend responsibilities:

* IFC parsing
* mesh generation
* voxelisation
* SDF generation
* graph extraction
* pathfinding
* optimisation

---

## 2.2 Sparse Spatial Representation

Do NOT use dense full-building voxel grids.

Preferred strategy:

* floor-by-floor decomposition
* sparse occupancy fields
* sparse SDFs
* graph abstractions

---

## 2.3 Hierarchical Routing

Routing should be multi-layered:

### Global Routing

* corridor graph
* risers
* service shafts
* major routing zones

### Local Routing

* voxel/SDF refinement
* obstacle avoidance
* smoothing

---

## 2.4 Semantic BIM Awareness

Routing should leverage IFC semantics:

* spaces
* storeys
* zones
* disciplines
* shafts
* corridors
* fire compartments

---

# 3. Recommended Technology Stack

# Frontend

## Framework

* React
* TypeScript

## 3D Rendering

Preferred:

* react-three-fiber

Alternative:

* Three.js

## BIM Viewer

Preferred:

* That Open Engine

Alternative:

* xeokit

## State Management

Preferred:

* Zustand

Alternative:

* Redux Toolkit

## UI

* TailwindCSS
* shadcn/ui

## Networking

* React Query / TanStack Query
* WebSockets

---

# Backend

## API Layer

Preferred:

* FastAPI

Reason:

* async support
* websocket support
* Python ecosystem compatibility

---

## IFC Processing

* IfcOpenShell

Responsibilities:

* IFC parsing
* geometry extraction
* metadata extraction
* IFC export

---

## Geometry Processing

* trimesh
* shapely

Responsibilities:

* mesh ops
* clipping
* slicing
* polygon conversion

---

## Numerical Processing

* NumPy
* SciPy

Responsibilities:

* distance transforms
* spatial analysis
* rasterisation

---

## Sparse Volumetrics

Preferred:

* OpenVDB

Alternative:

* NanoVDB

Responsibilities:

* sparse SDF storage
* large spatial fields

---

## Routing / Graphs

* NetworkX

Responsibilities:

* A*
* Steiner trees
* graph optimisation
* multi-floor routing

---

## Task Queue

Preferred:

* Celery + Redis

Responsibilities:

* long-running routing jobs
* preprocessing jobs
* asynchronous computation

---

## Database

Preferred:

* PostgreSQL + PostGIS

Responsibilities:

* metadata
* spatial indexing
* route storage
* user projects

---

## Object Storage

Preferred:

* S3 / MinIO

Responsibilities:

* IFC storage
* mesh caches
* exports

---

# 4. Core Data Flow

## IFC Ingestion Pipeline

```text
IFC Upload
    ↓
IfcOpenShell Parsing
    ↓
Mesh Extraction
    ↓
Floor Partitioning
    ↓
Obstacle Classification
    ↓
Voxelisation
    ↓
Sparse Occupancy Generation
    ↓
SDF Generation
    ↓
Corridor Skeletonization
    ↓
Routing Graph Construction
    ↓
Cache Persistence
```

---

# 5. Spatial Representation

# 5.1 Obstacle Extraction

Obstacle classes:

* IfcWall
* IfcColumn
* IfcBeam
* IfcSlab
* IfcCurtainWall
* Existing MEP systems

Ignore:

* furniture
* annotations
* proxies
* temporary objects

---

# 5.2 Floor-Based Partitioning

All routing should be decomposed per:

* IfcBuildingStorey

Reason:

* reduces memory usage
* improves scalability
* simplifies routing

---

# 5.3 Sparse Occupancy

Do NOT use dense voxel arrays.

Preferred structure:

```python
set[(x, y, z)]
```

or sparse volumetric grids.

---

# 5.4 Signed Distance Fields (SDF)

SDFs should be derived from:

* obstacle occupancy fields

Purpose:

* clearance-aware routing
* corridor extraction
* smooth path optimisation

---

# 5.5 Corridor Graph Extraction

Preferred approach:

* medial axis extraction from SDF

Pipeline:

```text
Obstacle Occupancy
    ↓
Distance Field
    ↓
Skeletonization
    ↓
Corridor Graph
```

Libraries:

* scikit-image
* SciPy

---

# 6. Routing System

# 6.1 Routing Layers

## Layer 1 — Global Graph

Represents:

* corridors
* shafts
* risers
* service zones

Used for:

* large-scale routing decisions

---

## Layer 2 — Local Refinement

Represents:

* local voxel fields
* local SDFs

Used for:

* obstacle avoidance
* fine path generation

---

# 6.2 Routing Algorithms

## Point-to-Point

Preferred:

* A*

Alternative:

* Dijkstra

---

## Multi-Terminal Networks

Preferred:

* Steiner tree approximation

Use cases:

* chilled water systems
* sprinkler systems
* cable tray routing

---

## Cost Functions

Routing costs should include:

* distance
* bend penalties
* congestion
* clearance preference
* riser penalties
* maintenance access

Example:

```python
cost =
    distance
    + bend_penalty
    + congestion_penalty
    - clearance_bonus
```

---

# 6.3 Clearance Handling

Use:

* hard minimum clearance
* SDF-based soft optimisation

Avoid:

* pure binary occupancy routing

---

# 6.4 Multi-Floor Routing

Vertical routing should occur only through:

* risers
* shafts
* designated service zones

Represent graph nodes as:

```python
(floor, x, y)
```

---

# 7. Frontend Features

# 7.1 IFC Viewer

Required:

* model loading
* visibility filters
* section planes
* clipping
* object selection
* metadata inspection

---

# 7.2 Route Authoring

Users should be able to:

* select endpoints
* specify discipline
* specify pipe size
* specify routing preferences

---

# 7.3 Route Visualisation

Display:

* routed paths
* pipe meshes
* clashes
* clearance overlays
* SDF heatmaps
* corridor skeletons

---

# 7.4 Debug Visualisation

Critical for development.

Display:

* occupancy voxels
* corridor graphs
* graph nodes
* route costs
* clearance fields

---

# 8. API Design

# 8.1 REST API

## Upload IFC

```http
POST /models
```

---

## Request Route

```http
POST /routes
```

Payload:

```json
{
  "modelId": "hospital_A",
  "start": [10, 5, 3],
  "end": [50, 12, 3],
  "diameter": 0.1,
  "discipline": "CHW"
}
```

---

## Fetch Route

```http
GET /routes/{id}
```

---

# 8.2 WebSockets

Use for:

* progress updates
* live routing feedback
* streaming previews

---

# 9. Preprocessing Pipeline

# 9.1 Geometry Cache

Precompute:

* meshes
* floor partitions
* occupancy
* SDFs
* corridor graphs

Do NOT compute on-demand repeatedly.

---

# 9.2 Geometry Export

Convert IFC → glTF/fragments.

Frontend should stream:

* optimised geometry
* not raw IFC processing

---

# 10. Storage Structure

Example:

```text
project/
├── ifc/
├── meshes/
├── sdf/
├── voxels/
├── graphs/
├── routes/
└── exports/
```

---

# 11. Performance Strategy

# 11.1 Chunked Spatial Processing

Partition floors into:

* zones
* chunks

Load only nearby spatial data during routing.

---

# 11.2 Sparse Fields

Avoid:

* giant dense arrays

Use:

* OpenVDB
* sparse hash maps
* chunked storage

---

# 11.3 Hierarchical Search

Global:

* corridor graph

Local:

* detailed refinement

---

# 12. Future Extensions

Potential future features:

* automatic riser detection
* hydraulic analysis
* pressure drop optimisation
* multi-pipe bundle routing
* cable routing
* duct routing
* clash-aware rerouting
* reinforcement-learning optimisation
* GPU acceleration
* IFC-native export generation

---

# 13. Suggested Initial MVP

## Phase 1

* IFC upload
* floor extraction
* obstacle voxelisation
* basic SDF generation
* simple A* routing
* route visualisation

---

## Phase 2

* corridor graph extraction
* multi-floor routing
* Steiner trees
* clearance-aware optimisation
* route smoothing

---

## Phase 3

* sparse OpenVDB integration
* distributed workers
* large-building scaling
* hydraulic constraints
* advanced optimisation

---

# 14. Recommended Development Priorities

1. Robust IFC ingestion
2. Stable geometry extraction
3. Sparse occupancy pipeline
4. SDF generation
5. Corridor graph extraction
6. A* routing
7. Viewer integration
8. Route smoothing
9. Multi-floor routing
10. Steiner network routing

---

# 15. Recommended Overall Philosophy

The platform should prioritise:

* scalable spatial representations
* semantic BIM awareness
* sparse computation
* hierarchical routing
* viewer responsiveness
* modular services

Avoid:

* monolithic architecture
* browser-heavy geometry computation
* dense full-building voxel systems
* tightly coupling routing to rendering
* recomputing spatial fields repeatedly
