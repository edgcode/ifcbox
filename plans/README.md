# IFCBox — Plans Index

Central map of the planning docs. **Read this first**, then the doc for whatever you're working on.

IFCBox is an MEP pipe-routing tool: given an IFC building model and two (or more) points on a storey, it produces a draft pipe route that avoids obstacles. Built solo, Python-first, in phases.

## Current focus

**Phase 3 — frontend + deployment.** Engine ([spec-pipeline.md](spec-pipeline.md)) and backend API ([spec-api.md](spec-api.md)) are built and tested. Next: the React frontend ([spec-frontend.md](spec-frontend.md)) and Dockerised Render + R2 + Postgres deployment ([spec-deploy.md](spec-deploy.md)).

## The docs

| Doc | What it covers | Status |
|---|---|---|
| [spec-pipeline.md](spec-pipeline.md) | **Phase 1** — the IFC parsing + routing pipeline (voxel grid → SDF → A* → pipe mesh). The spatial-intelligence core. | Built (PoC), being refactored |
| [spec-api.md](spec-api.md) | **Phase 2** — engine refactor + FastAPI backend. Engine layering, anchors/resolver, trunk vs independent routing, storage, REST + WS endpoints. | Built + tested |
| [spec-frontend.md](spec-frontend.md) | **Phase 3 frontend** — React + r3f viewer, click-to-pick + marker route authoring, clipping, occupancy/SDF overlays. Detailed plan. | Planning → building |
| [spec-deploy.md](spec-deploy.md) | **Phase 3 deploy/infra** — Dockerised on Render; R2 blobs + Postgres metadata; pluggable storage backends (local FS+SQLite for dev/tests); shared-secret auth. | Planning → building |
| [progress.md](progress.md) | Running progress + decision log (what's built, key decisions with rationale). | Living |
| [initial.md](initial.md) | Origin doc — the original idea and framing. | Historical |
| [../docs/architecture.md](../docs/architecture.md) | Structural reference for the code *as built* (modules, data flow, coordinate systems). | Living |

## How the docs relate

```
initial.md  ──>  spec-pipeline.md (Phase 1 core)          [built]
                       │
                       ▼
                 spec-api.md (Phase 2: engine refactor + API)   [built + tested]
                       │
                       ▼
                 spec-frontend.md (Phase 3 frontend)   ◀── current focus
                 spec-deploy.md   (Phase 3 deploy: Docker/Render/R2/Postgres)

progress.md         = what's actually done + why (cuts across all phases)
docs/architecture.md = how the built code is structured
```

## Phase roadmap (high level)

- **Phase 1** — Python routing pipeline. *Done as PoC.* (spec-pipeline.md)
- **Phase 2a** — Refactor PoC into a modular engine (PreparedFloor + route(), anchors, trunk/independent). (spec-api.md §2)
- **Phase 2b** — FastAPI backend wrapping the engine. (spec-api.md §3)
- **Phase 3** — Frontend (spec-frontend.md) + Dockerised Render/R2/Postgres deployment (spec-deploy.md). Then scale-out: multi-floor, multi-user, IFC write-back, queue/storage upgrades (spec-pipeline.md §5).

## Conventions

- `progress.md` is updated at the **end of a phase or session** (ask first — don't flood it while iterating).
- `docs/architecture.md` is updated whenever the **built** structure changes.
- Specs are the plan; `progress.md` is the record; `architecture.md` is the map.
