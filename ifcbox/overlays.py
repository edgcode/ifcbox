"""Overlay raster generation (occupancy / clearance) for the frontend.

Produces PNGs georeferenced to the voxel grid: row/col map directly to voxel
(y, x) with `origin='lower'` so voxel y=0 is at the image bottom — matching a
three.js plane whose +localY is site +y with default (V-up) UVs.
"""

from __future__ import annotations

import io

import numpy as np


def _encode(rgba: np.ndarray) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg

    buf = io.BytesIO()
    mpimg.imsave(buf, np.clip(rgba, 0, 1), format="png", origin="lower")
    return buf.getvalue()


def occupancy_png(occupancy: np.ndarray) -> bytes:
    """Red obstacles over translucent free space. occupancy is [nx, ny] bool."""
    nx, ny = occupancy.shape
    occ = occupancy.T  # [ny, nx]
    rgba = np.zeros((ny, nx, 4), dtype=np.float32)
    rgba[~occ] = (0.55, 0.55, 0.60, 0.25)
    rgba[occ] = (0.86, 0.20, 0.20, 0.85)
    return _encode(rgba)


def clearance_png(clearance: np.ndarray, occupancy: np.ndarray) -> bytes:
    """Viridis heatmap of the clearance field; obstacles transparent."""
    import matplotlib.cm as cm
    from matplotlib.colors import Normalize

    occ = occupancy.T
    cl = clearance.T.astype(float)
    free = ~occupancy
    vmax = float(np.percentile(clearance[free], 95)) if free.any() else 1.0
    rgba = cm.viridis(Normalize(vmin=0.0, vmax=max(vmax, 1e-6))(cl))
    rgba[..., 3] = 0.6
    rgba[occ] = (0.0, 0.0, 0.0, 0.0)
    return _encode(rgba.astype(np.float32))
