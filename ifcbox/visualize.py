"""PyVista visualisation — building obstacles + routed pipe mesh."""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# CHW pipe colour (blue)
PIPE_COLOUR = "#0077CC"
BUILDING_COLOUR = "lightgrey"
TERMINAL_COLOUR = "#FF6600"
WAYPOINT_COLOUR = "#FF0000"


def show(
    obstacle_meshes: list,
    pipe_mesh,
    waypoints: list[np.ndarray],
    title: str = "IFCBox — Route Preview",
    screenshot: str | None = None,
) -> None:
    """
    Open an interactive PyVista window showing building + pipe.

    obstacle_meshes: list[trimesh.Trimesh]
    pipe_mesh: trimesh.Trimesh
    waypoints: list of 3D world-coord np.ndarray (bend points)
    screenshot: if set, save PNG instead of opening interactive window
    """
    import pyvista as pv

    plotter = pv.Plotter(title=title)
    plotter.set_background("white")

    # Building obstacles — semi-transparent grey
    for mesh in obstacle_meshes:
        pv_mesh = _trimesh_to_pyvista(mesh)
        if pv_mesh is not None:
            plotter.add_mesh(
                pv_mesh,
                color=BUILDING_COLOUR,
                opacity=0.25,
                show_edges=False,
            )

    # Pipe mesh — solid blue
    if pipe_mesh is not None:
        pv_pipe = _trimesh_to_pyvista(pipe_mesh)
        if pv_pipe is not None:
            plotter.add_mesh(pv_pipe, color=PIPE_COLOUR, opacity=1.0, smooth_shading=True)

    # Waypoint bend-point spheres
    if len(waypoints) > 2:
        for wp in waypoints[1:-1]:  # skip endpoints, they have end-caps on the pipe
            sphere = pv.Sphere(radius=0.08, center=wp.tolist())
            plotter.add_mesh(sphere, color=WAYPOINT_COLOUR, opacity=1.0)

    # Endpoint markers
    for wp in [waypoints[0], waypoints[-1]]:
        sphere = pv.Sphere(radius=0.12, center=wp.tolist())
        plotter.add_mesh(sphere, color=TERMINAL_COLOUR, opacity=1.0)

    plotter.add_axes()
    plotter.add_text(title, font_size=10)

    if screenshot:
        plotter.show(screenshot=screenshot, auto_close=True)
        logger.info("Saved screenshot: %s", screenshot)
    else:
        plotter.show()


def _trimesh_to_pyvista(mesh):
    """Convert a trimesh.Trimesh to a pyvista.PolyData."""
    try:
        import pyvista as pv
        faces = np.hstack([
            np.full((len(mesh.faces), 1), 3, dtype=np.int64),
            mesh.faces.astype(np.int64),
        ])
        return pv.PolyData(mesh.vertices.astype(np.float32), faces)
    except Exception as e:
        logger.debug("trimesh→pyvista conversion failed: %s", e)
        return None
