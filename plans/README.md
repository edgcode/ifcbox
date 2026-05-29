# IFCBox — Plans Index

Central map of the planning docs. **Read this first**, then the doc for whatever you're working on.

IFCBox is an MEP pipe-routing tool: given an IFC building model and two (or more) points on a storey, it produces a draft pipe route that avoids obstacles. Built solo, Python-first, in phases.

## Current focus

**Phase 2a/2b — engine refactor + backend API** (API-first; no frontend yet). See [spec-api.md](spec-api.md).

## The docs

| Doc | What it covers | Status |
|---|---|---|
| [spec-pipeline.md](spec-pipeline.md) | **Phase 1** — the IFC parsing + routing pipeline (voxel grid → SDF → A* → pipe mesh). The spatial-intelligence core. | Built (PoC), being refactored |
| [spec-api.md](spec-api.md) | **Phase 2** — refactor the pipeline into a clean engine, then wrap it in a FastAPI backend. Engine layering, anchors/resolver, trunk vs independent routing, storage, REST + WS endpoints. | Planning → building |
| [spec-frontend.md](spec-frontend.md) | **Frontend** — React + r3f BIM viewer / route authoring UI. Aspirational outline; the API in spec-api.md is designed to serve it. | Outline only |
| [progress.md](progress.md) | Running progress + decision log (what's built, key decisions with rationale). | Living |
| [initial.md](initial.md) | Origin doc — the original idea and framing. | Historical |
| [../docs/architecture.md](../docs/architecture.md) | Structural reference for the code *as built* (modules, data flow, coordinate systems). | Living |

## How the docs relate

```
initial.md  ──>  spec-pipeline.md (Phase 1 core)
                       │
                       ▼
                 spec-api.md (Phase 2: engine refactor + API)  ◀── current focus
                       │
                       ▼
                 spec-frontend.md (frontend, designed against the API)

progress.md         = what's actually done + why (cuts across all phases)
docs/architecture.md = how the built code is structured
```

## Phase roadmap (high level)

- **Phase 1** — Python routing pipeline. *Done as PoC.* (spec-pipeline.md)
- **Phase 2a** — Refactor PoC into a modular engine (PreparedFloor + route(), anchors, trunk/independent). (spec-api.md §2)
- **Phase 2b** — FastAPI backend wrapping the engine. (spec-api.md §3)
- **Phase 3** — Frontend, then scale-out (multi-floor, multi-user, IFC write-back, queue/storage upgrades). (spec-frontend.md, spec-pipeline.md §5)

## Conventions

- `progress.md` is updated at the **end of a phase or session** (ask first — don't flood it while iterating).
- `docs/architecture.md` is updated whenever the **built** structure changes.
- Specs are the plan; `progress.md` is the record; `architecture.md` is the map.
