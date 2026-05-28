"""Direction-aware A* pathfinding — 4-connected, 90° bends only, bend-penalised."""

from __future__ import annotations

import heapq
import logging
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 4-connected moves: (dx, dy, direction_index)
# direction indices: 0=+X, 1=-X, 2=+Y, 3=-Y
MOVES = [(1, 0, 0), (-1, 0, 1), (0, 1, 2), (0, -1, 3)]

REVERSE = {0: 1, 1: 0, 2: 3, 3: 2}
NO_DIR = -1


def find_path(
    cost_grid: np.ndarray,
    occupancy: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    bend_penalty: float = 50.0,
    seeds: list[tuple[int, int]] | None = None,
) -> Optional[list[tuple[int, int]]]:
    """
    Direction-aware A* from start (or a set of network seeds) to end.

    When `seeds` is provided the priority queue is pre-seeded with every voxel
    in the list at cost 0 — this implements multi-source A* for Steiner-tree
    routing.  The returned path runs from the best seed to end; the caller can
    identify the branch point as the first seed voxel on the path.

    State: (vx, vy, direction). A 90° turn adds bend_penalty.
    U-turns (180°) are prohibited.
    """
    nx, ny = cost_grid.shape

    start = _ensure_passable(cost_grid, occupancy, start)
    end   = _ensure_passable(cost_grid, occupancy, end)
    if start is None or end is None:
        logger.warning("Start or end has no reachable passable cell")
        return None

    if start == end:
        return [start]

    g: dict[tuple[int, int, int], float] = {}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    pq: list[tuple[float, tuple[int, int, int]]] = []

    # Seed from every network voxel (Steiner mode) or just the single start
    seed_set = set(seeds) if seeds else set()
    for sx, sy in (seed_set if seed_set else {start}):
        state = (sx, sy, NO_DIR)
        g[state] = 0.0
        heapq.heappush(pq, (_manhattan((sx, sy), end), state))

    while pq:
        f_cur, state = heapq.heappop(pq)
        vx, vy, cur_dir = state

        if (vx, vy) == end:
            return _reconstruct(came_from, state)

        g_cur = g.get(state, np.inf)
        if f_cur > g_cur + _manhattan((vx, vy), end) + 1e-6:
            continue

        for dx, dy, new_dir in MOVES:
            nx_ = vx + dx
            ny_ = vy + dy
            if not (0 <= nx_ < nx and 0 <= ny_ < ny):
                continue
            if cur_dir != NO_DIR and new_dir == REVERSE[cur_dir]:
                continue

            cell_cost = float(cost_grid[nx_, ny_])
            if np.isinf(cell_cost):
                continue

            is_turn = (cur_dir != NO_DIR and new_dir != cur_dir)
            new_g = g_cur + cell_cost + (bend_penalty if is_turn else 0.0)
            new_state = (nx_, ny_, new_dir)

            if new_g < g.get(new_state, np.inf):
                g[new_state] = new_g
                came_from[new_state] = state
                heapq.heappush(pq, (new_g + _manhattan((nx_, ny_), end), new_state))

    logger.warning("No path found from %s to %s", start, end)
    return None


# ── Endpoint nudging ──────────────────────────────────────────────────────────

MIN_COMPONENT = 50  # reject nudge targets in components smaller than this


def _ensure_passable(
    cost_grid: np.ndarray,
    occupancy: np.ndarray,
    point: tuple[int, int],
    max_radius: int = 60,
) -> Optional[tuple[int, int]]:
    """
    Return a passable voxel at or near point, guaranteed to be in a reasonably-
    sized connected component of the passable (finite-cost) graph.

    Three-pass strategy:
    1. If point is already free, passable, and in a large component — return it.
    2. BFS through finite-cost cells to find the nearest free cell, then verify
       its component is large enough. (Handles: inside obstacle, isolated pocket
       with door-zone exits.)
    3. If no finite-cost path out exists (e.g. pocket with zero door zones),
       BFS through ALL cells (including infinite-cost walls) to find the nearest
       free cell that IS in a large component. (Handles: fully walled-off pocket.)
    """
    nx, ny = cost_grid.shape

    def component_size(pt: tuple[int, int], limit: int = MIN_COMPONENT + 1) -> int:
        """Fast BFS that stops counting at limit."""
        seen: set[tuple[int, int]] = {pt}
        q: deque[tuple[int, int]] = deque([pt])
        while q and len(seen) < limit:
            x, y = q.popleft()
            for dx, dy, _ in MOVES:
                nx_, ny_ = x + dx, y + dy
                if (0 <= nx_ < nx and 0 <= ny_ < ny
                        and (nx_, ny_) not in seen
                        and not np.isinf(cost_grid[nx_, ny_])):
                    seen.add((nx_, ny_))
                    q.append((nx_, ny_))
        return len(seen)

    def is_good(pt: tuple[int, int]) -> bool:
        return (not occupancy[pt]
                and not np.isinf(cost_grid[pt])
                and component_size(pt) >= MIN_COMPONENT)

    # Pass 1: already good
    if is_good(point):
        return point

    # Pass 2: BFS through finite-cost cells
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque([point])
    visited.add(point)
    while queue:
        x, y = queue.popleft()
        if not occupancy[x, y] and not np.isinf(cost_grid[x, y]):
            if component_size((x, y)) >= MIN_COMPONENT:
                if (x, y) != point:
                    logger.debug("Nudged (passable BFS) %s → %s", point, (x, y))
                return (x, y)
        for dx, dy, _ in MOVES:
            nx_ = x + dx
            ny_ = y + dy
            if (0 <= nx_ < nx and 0 <= ny_ < ny
                    and (nx_, ny_) not in visited
                    and abs(nx_ - point[0]) <= max_radius
                    and abs(ny_ - point[1]) <= max_radius
                    and not np.isinf(cost_grid[nx_, ny_])):
                visited.add((nx_, ny_))
                queue.append((nx_, ny_))

    # Pass 3: pocket with no finite-cost exits — search through walls too
    logger.debug("Pass-3 nudge (through walls) for %s", point)
    visited2: set[tuple[int, int]] = set()
    queue2: deque[tuple[int, int]] = deque([point])
    visited2.add(point)
    while queue2:
        x, y = queue2.popleft()
        if is_good((x, y)):
            logger.debug("Nudged (wall-crossing) %s → %s", point, (x, y))
            return (x, y)
        for dx, dy, _ in MOVES:
            nx_ = x + dx
            ny_ = y + dy
            if (0 <= nx_ < nx and 0 <= ny_ < ny
                    and (nx_, ny_) not in visited2
                    and abs(nx_ - point[0]) <= max_radius
                    and abs(ny_ - point[1]) <= max_radius):
                visited2.add((nx_, ny_))
                queue2.append((nx_, ny_))

    logger.warning("Could not nudge %s to any large passable component", point)
    return _nearest_free(occupancy, point, max_radius)


def _nearest_free(
    occupancy: np.ndarray,
    start: tuple[int, int],
    max_radius: int = 60,
) -> Optional[tuple[int, int]]:
    """BFS to find the nearest free (non-occupied) voxel."""
    nx, ny = occupancy.shape
    visited: set[tuple[int, int]] = {start}
    queue: deque[tuple[int, int]] = deque([start])

    while queue:
        x, y = queue.popleft()
        if not occupancy[x, y]:
            return (x, y)
        for dx, dy, _ in MOVES:
            nx_ = x + dx
            ny_ = y + dy
            if (0 <= nx_ < nx and 0 <= ny_ < ny
                    and (nx_, ny_) not in visited
                    and abs(nx_ - start[0]) <= max_radius
                    and abs(ny_ - start[1]) <= max_radius):
                visited.add((nx_, ny_))
                queue.append((nx_, ny_))
    return None


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> float:
    return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))


def _reconstruct(
    came_from: dict,
    end_state: tuple[int, int, int],
) -> list[tuple[int, int]]:
    path = []
    cur = end_state
    while cur in came_from:
        path.append((cur[0], cur[1]))
        cur = came_from[cur]
    path.append((cur[0], cur[1]))
    path.reverse()
    return path
