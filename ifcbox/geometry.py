"""Building-shell geometry export for the frontend.

Exports a per-element glTF (one named mesh per obstacle, keyed by IFC GlobalId)
so the viewer can recolour individual walls, plus a `walls.json` sidecar of the
per-element attributes. Z-up is retained (matches Revit-exported IFC).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_shell_scene(geom):
    """trimesh.Scene of the floor's obstacles in world coords, one node per element."""
    import trimesh

    scene = trimesh.Scene()
    st = geom.site_transform
    for mesh, el in zip(geom.meshes, geom.elements):
        scene.add_geometry(st.world_mesh(mesh), geom_name=el["id"], node_name=el["id"])
    return scene


def wall_attributes(geom) -> dict:
    """{element_id: {id, ifc_type, thickness_m, wall_type, wall_type_name, fire_rating}}."""
    return {el["id"]: el for el in geom.elements}


def export_floor_shell(geom, shell_path: str | Path, walls_path: str | Path | None = None) -> Path:
    """Write the per-element building shell (.glb); optionally the walls.json sidecar."""
    shell_path = Path(shell_path)
    scene = build_shell_scene(geom)
    scene.export(shell_path)
    logger.info("Exported per-element shell glTF (%d elements) → %s",
                len(geom.elements), shell_path)
    if walls_path is not None:
        Path(walls_path).write_text(json.dumps(wall_attributes(geom)))
    return shell_path
