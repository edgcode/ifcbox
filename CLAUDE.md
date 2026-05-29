# IFCBox — Working Rules

IFC pipe-routing pipeline. MEP engineer tool: route a pipe A→B through a building floor, avoiding obstacles. See `plans/README.md` for the full map.

## Always check the plans folder first

Before starting any non-trivial work, read:

- **`plans/README.md`** — the central index. Start here; it maps all the plan docs and points to the current focus.
- **`plans/spec-pipeline.md`** — Phase 1 spec: the IFC parsing + routing pipeline (the spatial core).
- **`plans/spec-api.md`** — Phase 2 spec: engine refactor + FastAPI backend (current focus).
- **`plans/spec-frontend.md`** — frontend outline (the API is designed to serve it).
- **`plans/progress.md`** — what has been built, key technical decisions with rationale, and next steps. Read this to understand current state before proposing changes.

The specs are the source of truth for *what we are building* and *what we are explicitly NOT building yet* (each has a "what we are NOT building" table). Do not let deferred features creep into the current phase. If a request conflicts with a locked decision in a spec, flag the conflict rather than silently overriding it.

## Updating progress.md

`plans/progress.md` tracks real progress and the decision log. **Do not update it on every iteration** — that floods it with churn while we are still iterating on an approach.

- **Ask before updating** `progress.md`.
- Normally we update it at the **end of a phase or a working session**, once decisions have settled.
- When you do update it, record decisions *with their rationale* (the "why"), not just the "what".

## Maintain docs/architecture.md

`docs/architecture.md` describes the system structure: modules, data flow, coordinate systems, and key data types. Keep it current when the architecture changes (new module, changed data flow, new coordinate convention, changed core data structure). Unlike `progress.md`, architecture.md may be updated as structure changes — but keep it a structural reference, not a changelog.

## Quick orientation

- Pipeline lives in `ifcbox/pipeline/` (loader → voxelizer → sdf → zoning → router → smoother → mesh → export).
- CLI entry points: `route.py` (single point-to-point) and `demo_routes.py` (batch demo).
- Outputs land in `output/<model-stem>/`.
- Stack: ifcopenshell, trimesh, numpy, scipy, pyvista, networkx, scikit-image. Python-first; web platform (FastAPI + React) is Phase 2.
