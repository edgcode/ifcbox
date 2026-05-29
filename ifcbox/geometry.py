"""Building-shell geometry export for the frontend.

Serves the floor's obstacle meshes as a single glTF so the browser renders
server-generated geometry (not raw IFC). Z-up is retained (matches Revit-
exported IFC); the frontend flips to Y-up if it needs to.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_shell_mesh(meshes: list, site_transform):
    """Concatenate site-aligned obstacle meshes into one world-coord trimesh."""
    import trimesh

    if not meshes:
        return trimesh.Trimesh()
    world = [site_transform.world_mesh(m) for m in meshes]
    return trimesh.util.concatenate(world)


def export_floor_shell(meshes: list, site_transform, path: str | Path) -> Path:
    """Write the floor's building shell to a glTF (.glb) in world coordinates."""
    from ifcbox.pipeline.export import export_gltf

    path = Path(path)
    mesh = build_shell_mesh(meshes, site_transform)
    export_gltf(mesh, path)
    logger.info("Exported floor shell glTF (%d faces) → %s", len(mesh.faces), path)
    return path
