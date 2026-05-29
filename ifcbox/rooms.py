"""Room-type classification + footprint raster overlay.

Classifies IfcSpace names (DE + EN) into a small set of room types and rasterises
each space footprint (sliced at the routing elevation) into a class grid, then a
coloured PNG overlay — reusing the same georeferencing as the occupancy/SDF
overlays (see ifcbox/overlays.py).
"""

from __future__ import annotations

import io
import re

import numpy as np

# Ordered classes; grid index = position+1 (0 = background/none).
ROOM_CLASSES = [
    ("bedroom", "Bedroom", "#60a5fa"),
    ("bathroom", "Bathroom", "#22d3ee"),
    ("kitchen_living", "Kitchen / living", "#f59e0b"),
    ("circulation", "Circulation", "#a3e635"),
    ("stair_shaft", "Stair / shaft", "#f87171"),
    ("balcony", "Balcony / outdoor", "#34d399"),
    ("storage_technical", "Storage / technical", "#c084fc"),
    ("other", "Other", "#9ca3af"),
]

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("bathroom", re.compile(r"(bade|\bbad\b|bad[:\s]|\bwc\b|wc/|dusche|\bdu\b|bathroom|toilet|shower)", re.I)),
    ("kitchen_living", re.compile(r"(wohnen|k[üu]che|kueche|kitchen|living|wohnzimmer|essen|dining)", re.I)),
    ("circulation", re.compile(r"(flur|korridor|diele|gang|vorraum|foyer|hausflur|erschlie|corridor|hallway|lobby)", re.I)),
    ("stair_shaft", re.compile(r"(treppe|treppenraum|treppenhaus|schacht|shaft|stair|aufzug|lift|elevat|riser)", re.I)),
    ("balcony", re.compile(r"(balkon|terrasse|loggia|balcony|terrace)", re.I)),
    ("storage_technical", re.compile(r"(abstellraum|\bar\b|lager|technik|hwr|hausanschl|keller|storage|technical|plant|utility)", re.I)),
    ("bedroom", re.compile(r"(schlafzimmer|kinderzimmer|\bzimmer\b|bedroom|\broom\b)", re.I)),
]

_KEY_TO_INDEX = {key: i + 1 for i, (key, _, _) in enumerate(ROOM_CLASSES)}


def classify_index(name: str) -> int:
    """Return the 1-based class index for a space name (defaults to 'other')."""
    n = (name or "").strip()
    for key, pat in _PATTERNS:
        if pat.search(n):
            return _KEY_TO_INDEX[key]
    return _KEY_TO_INDEX["other"]


def build_room_class_grid(model, meta, pipe_z: float, site_xform) -> np.ndarray:
    """Rasterise classified IfcSpace footprints at pipe_z into an int8 grid."""
    import ifcopenshell.geom
    import trimesh

    from ifcbox.pipeline.voxelizer import _rasterize_section_3d

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    grid = np.zeros(meta.shape, dtype=np.int8)
    for space in model.by_type("IfcSpace"):
        idx = classify_index(space.Name or "")
        try:
            shape = ifcopenshell.geom.create_shape(settings, space)
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            faces = np.array(shape.geometry.faces).reshape(-1, 3)
            if len(verts) == 0:
                continue
            mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            mesh = site_xform.transform_mesh(mesh)
            if mesh.bounds[1][2] < pipe_z - 0.5 or mesh.bounds[0][2] > pipe_z + 0.5:
                continue
            section = mesh.section(plane_origin=[0, 0, pipe_z], plane_normal=[0, 0, 1])
            if section is not None and len(section.vertices) >= 3:
                mask = np.zeros(meta.shape, dtype=bool)
                _rasterize_section_3d(section, mask, meta)
                grid[mask] = idx
        except Exception:
            pass
    return grid


def rooms_png(room_class: np.ndarray) -> bytes:
    """Colour a class grid [nx, ny] into a translucent PNG (background transparent)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg

    nx, ny = room_class.shape
    cls = room_class.T  # [ny, nx]
    rgba = np.zeros((ny, nx, 4), dtype=np.float32)
    for i, (_, _, hexcol) in enumerate(ROOM_CLASSES):
        idx = i + 1
        m = cls == idx
        if not m.any():
            continue
        r = int(hexcol[1:3], 16) / 255
        g = int(hexcol[3:5], 16) / 255
        b = int(hexcol[5:7], 16) / 255
        rgba[m] = (r, g, b, 0.55)

    buf = io.BytesIO()
    mpimg.imsave(buf, np.clip(rgba, 0, 1), format="png", origin="lower")
    return buf.getvalue()


def export_rooms_png(model, meta, pipe_z: float, site_xform, path) -> None:
    from pathlib import Path

    grid = build_room_class_grid(model, meta, pipe_z, site_xform)
    Path(path).write_bytes(rooms_png(grid))
