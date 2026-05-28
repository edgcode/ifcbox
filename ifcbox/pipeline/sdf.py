"""Signed distance / clearance field generation from occupancy grid."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def compute_clearance_field(occupancy: np.ndarray) -> np.ndarray:
    """
    Compute Euclidean distance from each free voxel to the nearest obstacle.

    Returns float array, same shape as occupancy.
    Obstacle voxels have value 0. Open space values are in voxel units.
    """
    from scipy.ndimage import distance_transform_edt
    clearance = distance_transform_edt(~occupancy).astype(np.float32)
    logger.info(
        "Clearance field: min=%.2f max=%.2f mean=%.2f voxels",
        clearance.min(), clearance.max(), clearance[~occupancy].mean(),
    )
    return clearance


def build_cost_grid(
    clearance: np.ndarray,
    occupancy: np.ndarray,
    wall_costs: np.ndarray | None = None,
    clearance_weight: float = 2.0,
    wall_penalty: float = 500.0,
) -> np.ndarray:
    """
    Build A* cost grid from clearance field.

    Free cells: cost = 1.0 + clearance_weight / (clearance + epsilon)
    Obstacle cells: per-voxel cost from wall_costs (typed by wall thickness),
                    or flat wall_penalty if wall_costs is not provided.
    """
    eps = 1e-3
    cost = (1.0 + clearance_weight / (clearance + eps)).astype(np.float32)
    if wall_costs is not None:
        cost[occupancy] = wall_costs[occupancy]
    else:
        cost[occupancy] = wall_penalty
    return cost


def debug_heatmap(clearance: np.ndarray, occupancy: np.ndarray, path: str):
    """Save clearance field as a heatmap PNG for debugging."""
    import matplotlib.pyplot as plt

    display = clearance.copy().astype(float)
    display[occupancy] = np.nan

    fig, ax = plt.subplots(figsize=(12, 12))
    im = ax.imshow(display.T, origin="lower", cmap="viridis", interpolation="nearest")
    plt.colorbar(im, ax=ax, label="clearance (voxels)")
    ax.set_title("Clearance field")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("Saved clearance heatmap: %s", path)
