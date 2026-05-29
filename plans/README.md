# IFCBox — Plans Index

Central map of the planning docs. **Read this first**, then the doc for whatever you're working on.

IFCBox is an MEP pipe-routing tool: given an IFC building model and two (or more) points on a storey, it produces a draft pipe route that avoids obstacles. Built solo, Python-first, in phases.

## Current focus

**Phase 3 shipped (with caveats).** Engine ([spec-pipeline.md](spec-pipeline.md)), backend API ([spec-api.md](spec-api.md)), React frontend ([spec-frontend.md](spec-frontend.md)) and the Dockerised Render + R2 + Neon Postgres deployment ([spec-deploy.md](spec-deploy.md)) are all built. The apartment auto-routing demo ([spec-frontend.md §10](spec-frontend.md)) is built. The **hosted app on the free Render tier is slow/unstable** — the 38 MB test IFC OOMs prep at 512 MB; smaller IFCs work. Local mode (Vite + uvicorn + FS/SQLite) is the recommended way to try it.

## The docs

| Doc | What it covers | Status |
|---|---|---|
| [spec-pipeline.md](spec-pipeline.md) | **Phase 1** — the IFC parsing + routing pipeline (voxel grid → SDF → A* → pipe mesh). The spatial-intelligence core. | Built |
| [spec-api.md](spec-api.md) | **Phase 2** — engine refactor + FastAPI backend. Engine layering, anchors/resolver, trunk vs independent routing, storage, REST + WS endpoints. | Built + tested (19 tests) |
| [spec-frontend.md](spec-frontend.md) | **Phase 3 frontend** — React + r3f viewer, click-to-pick + marker route authoring, clipping, overlays, apartment auto-routing demo. | Built (F-1…F-8, A-1…A-3) |
| [spec-deploy.md](spec-deploy.md) | **Phase 3 deploy/infra** — Dockerised on Render; R2 blobs + Neon Postgres metadata; pluggable storage backends; shared-secret auth. | Built (D-1…D-5) + deployed (D-6 partial; free-tier OOM caveat) |
| [progress.md](progress.md) | Running progress + decision log (what's built, key decisions with rationale). | Living |
| [initial.md](initial.md) | Origin doc — the original idea and framing. | Historical |
| [../docs/architecture.md](../docs/architecture.md) | Structural reference for the code *as built* (modules, data flow, coordinate systems). | Living |

## How the docs relate

```
initial.md  ──>  spec-pipeline.md (Phase 1 core)                       [built]
                       │
                       ▼
                 spec-api.md (Phase 2: engine refactor + API)          [built + tested]
                       │
                       ▼
                 spec-frontend.md (Phase 3 frontend + apartment demo)  [built]
                 spec-deploy.md   (Phase 3 deploy: Docker/Render/R2/Neon) [built; hosted on free tier, slow]

progress.md         = what's actually done + why (cuts across all phases)
docs/architecture.md = how the built code is structured
```

## Phase roadmap (high level)

- **Phase 1** — Python routing pipeline. *Done as PoC.* (spec-pipeline.md)
- **Phase 2a** — Refactor PoC into a modular engine (PreparedFloor + route(), anchors, trunk/independent). *Done.* (spec-api.md §2)
- **Phase 2b** — FastAPI backend wrapping the engine. *Done + tested.* (spec-api.md §3)
- **Phase 3** — Frontend + Docker/Render/R2/Neon deployment + apartment auto-routing demo. *Done; hosted, with a free-tier OOM caveat for large IFCs.* (spec-frontend.md, spec-deploy.md)
- **Next (scale-out)** — multi-floor risers, real multi-user auth, IFC write-back, Render Standard tier or queue/storage upgrades. (spec-pipeline.md §5)

## Conventions

- `progress.md` is updated at the **end of a phase or session** (ask first — don't flood it while iterating).
- `docs/architecture.md` is updated whenever the **built** structure changes.
- Specs are the plan; `progress.md` is the record; `architecture.md` is the map.
