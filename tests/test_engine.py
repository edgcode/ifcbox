"""Engine-level tests: PreparedFloor, route parity, save/load, trunk vs independent."""

from __future__ import annotations

import numpy as np
import pytest

from ifcbox.engine import PreparedFloor, RouteParams, build_route_mesh, prepare_floor, route
from ifcbox.resolver import AnchorError, PointAnchor, RoomAnchor, TerminalAnchor

from .conftest import BASELINE_END_XYZ, BASELINE_LENGTH, BASELINE_START_XYZ, TEST_FLOOR


def test_prepared_floor_shapes(prepared_floor):
    p = prepared_floor
    shape = p.meta.shape
    assert p.occupancy.dtype == bool and p.occupancy.shape == shape
    for mask in (p.corridor, p.door_zone, p.forbidden):
        assert mask.dtype == bool and mask.shape == shape
    assert p.clearance.shape == shape and p.wall_costs.shape == shape
    assert len(p.terminals) > 0
    assert len(p.spaces) > 0
    assert p.floor_index == TEST_FLOOR


def test_route_point_parity(prepared_floor):
    """Refactored engine must reproduce the pre-refactor reference route."""
    res = route(prepared_floor, PointAnchor(BASELINE_START_XYZ),
                [PointAnchor(BASELINE_END_XYZ)], mode="trunk")
    assert len(res.segments) == 1
    seg = res.segments[0]
    assert len(seg.waypoints) == 3
    assert res.total_length == pytest.approx(BASELINE_LENGTH, abs=0.05)
    start, end = np.array(seg.waypoints[0]), np.array(seg.waypoints[-1])
    assert start[:2] == pytest.approx([5.29, 41.73], abs=0.1)
    assert end[:2] == pytest.approx([9.36, 42.41], abs=0.1)


def test_save_load_roundtrip(prepared_floor, tmp_path):
    prepared_floor.save(tmp_path)
    reloaded = PreparedFloor.load(tmp_path)

    src, dst = PointAnchor(BASELINE_START_XYZ), PointAnchor(BASELINE_END_XYZ)
    a = route(prepared_floor, src, [dst])
    b = route(reloaded, src, [dst])
    assert np.allclose(a.segments[0].waypoints, b.segments[0].waypoints)
    assert np.array_equal(prepared_floor.occupancy, reloaded.occupancy)
    assert prepared_floor.terminals.keys() == reloaded.terminals.keys()


def test_trunk_shorter_than_independent(prepared_floor):
    src = PointAnchor(BASELINE_START_XYZ)
    targets = [
        PointAnchor((9.311, 42.449, 6.92)),
        PointAnchor((8.613, 39.262, 6.92)),
        PointAnchor((1.113, 39.978, 6.92)),
    ]
    trunk = route(prepared_floor, src, targets, mode="trunk")
    indep = route(prepared_floor, src, targets, mode="independent")

    assert len(trunk.segments) == 3 and len(indep.segments) == 3
    assert len(trunk.branch_points) == 2          # first seg is root, two branch off
    assert trunk.segments[0].branch_from is None
    assert all(s.branch_from is not None for s in trunk.segments[1:])
    assert len(indep.branch_points) == 0
    assert trunk.total_length <= indep.total_length


def test_room_anchor_resolves(prepared_floor):
    names = {v["name"]: gid for gid, v in prepared_floor.spaces.items()}
    flur = next((gid for nm, gid in names.items() if nm.startswith("Flur")), None)
    bad = next((gid for nm, gid in names.items() if nm.startswith("Bad")), None)
    assert flur and bad, "expected Flur + Bad spaces on the test floor"

    res = route(prepared_floor, RoomAnchor(flur), [RoomAnchor(bad)])
    assert not res.unreachable_targets
    assert res.total_length > 0
    assert len(res.segments[0].waypoints) >= 2


def test_unknown_terminal_raises(prepared_floor):
    with pytest.raises(AnchorError):
        route(prepared_floor, TerminalAnchor("NOPE"), [PointAnchor(BASELINE_END_XYZ)])


def test_corridor_weight_is_a_param(prepared_floor):
    """corridor_weight should be tunable (exposed at route time, not baked in)."""
    cheap = route(prepared_floor, PointAnchor(BASELINE_START_XYZ),
                  [PointAnchor(BASELINE_END_XYZ)],
                  params=RouteParams(corridor_weight=0.05))
    pricey = route(prepared_floor, PointAnchor(BASELINE_START_XYZ),
                   [PointAnchor(BASELINE_END_XYZ)],
                   params=RouteParams(corridor_weight=1.0))
    assert cheap.segments and pricey.segments  # both route; weight changes preference


def test_build_route_mesh_nonempty(prepared_floor):
    res = route(prepared_floor, PointAnchor(BASELINE_START_XYZ),
                [PointAnchor(BASELINE_END_XYZ)])
    mesh = build_route_mesh(res)
    assert len(mesh.vertices) > 0 and len(mesh.faces) > 0
