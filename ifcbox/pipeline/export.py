"""Export routing results to JSON waypoints and glTF mesh."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def export_json(
    waypoints: list[np.ndarray],
    path: str | Path,
    diameter: float = 0.1,
    discipline: str = "generic",
    storey_name: str = "",
) -> None:
    """Write route waypoints as JSON."""
    data = {
        "discipline": discipline,
        "diameter_m": diameter,
        "storey": storey_name,
        "waypoint_count": len(waypoints),
        "waypoints": [[round(float(v), 4) for v in wp] for wp in waypoints],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Exported JSON waypoints: %s", path)


def export_gltf(mesh, path: str | Path) -> None:
    """Export pipe mesh as binary glTF (.glb)."""
    import trimesh

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    path = str(path)
    if not path.endswith(".glb"):
        path = path.rsplit(".", 1)[0] + ".glb"
    mesh.export(path)
    logger.info("Exported glTF mesh: %s", path)
