"""API end-to-end tests via TestClient: upload → prepare → route + error contracts."""

from __future__ import annotations

import time

import pytest

from .conftest import BASELINE_END_XYZ, BASELINE_LENGTH, BASELINE_START_XYZ, TEST_FLOOR

API = "/api/v1"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:        # context manager runs lifespan → init_db
        yield c


@pytest.fixture(scope="module")
def prepared_model(client, model_ifc_path):
    """Upload the model and prepare the test floor once for the module."""
    with open(model_ifc_path, "rb") as f:
        r = client.post(f"{API}/models",
                        files={"file": ("model.ifc", f, "application/octet-stream")})
    assert r.status_code == 200
    mid = r.json()["model_id"]

    assert client.post(f"{API}/models/{mid}/floors/{TEST_FLOOR}/prepare").status_code == 202
    status = None
    for _ in range(180):
        status = client.get(f"{API}/models/{mid}/floors/{TEST_FLOOR}").json()["status"]
        if status in ("ready", "error"):
            break
        time.sleep(1)
    assert status == "ready"
    return mid


# ── fast contract tests (no prep) ─────────────────────────────────────────────
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_rejects_non_ifc(client):
    r = client.post(f"{API}/models",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_get_unknown_model_404(client):
    assert client.get(f"{API}/models/deadbeef").status_code == 404


# ── prepared-floor tests ──────────────────────────────────────────────────────
def test_floor_detail_ready(client, prepared_model):
    d = client.get(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}").json()
    assert d["status"] == "ready"
    assert len(d["spaces"]) > 0
    assert len(d["terminals"]) > 0


def test_route_unprepared_floor_409(client, prepared_model):
    # floor 5 of the same model was never prepared
    r = client.post(f"{API}/models/{prepared_model}/floors/5/routes", json={
        "source": {"type": "point", "xyz": list(BASELINE_START_XYZ)},
        "targets": [{"type": "point", "xyz": list(BASELINE_END_XYZ)}],
    })
    assert r.status_code == 409


def test_geometry_glb(client, prepared_model):
    r = client.get(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}/geometry")
    assert r.status_code == 200
    assert len(r.content) > 1000


def test_point_route_matches_baseline(client, prepared_model):
    r = client.post(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}/routes", json={
        "source": {"type": "point", "xyz": list(BASELINE_START_XYZ)},
        "targets": [{"type": "point", "xyz": list(BASELINE_END_XYZ)}],
        "mode": "trunk",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["total_length_m"] == pytest.approx(BASELINE_LENGTH, abs=0.05)
    assert len(body["segments"]) == 1
    # fetch + mesh + history
    rid = body["route_id"]
    assert client.get(f"{API}/routes/{rid}").status_code == 200
    assert client.get(f"{API}/routes/{rid}/mesh").status_code == 200
    assert len(client.get(f"{API}/models/{prepared_model}/routes").json()) >= 1


def test_room_trunk_route(client, prepared_model):
    detail = client.get(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}").json()
    by_name = {s["name"]: s["id"] for s in detail["spaces"]}
    flur = next((sid for nm, sid in by_name.items() if nm.startswith("Flur")), None)
    rooms = [sid for nm, sid in by_name.items() if nm.startswith(("Bad", "Zimmer"))][:3]
    assert flur and len(rooms) >= 2

    r = client.post(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}/routes", json={
        "source": {"type": "room", "id": flur},
        "targets": [{"type": "room", "id": s} for s in rooms],
        "mode": "trunk",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["segments"]) == len(rooms)
    assert len(body["branch_points"]) == len(rooms) - 1


def test_bad_anchor_422(client, prepared_model):
    r = client.post(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}/routes", json={
        "source": {"type": "terminal", "id": "DOES_NOT_EXIST"},
        "targets": [{"type": "point", "xyz": list(BASELINE_END_XYZ)}],
    })
    assert r.status_code == 422


def test_prepare_idempotent(client, prepared_model):
    r = client.post(f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}/prepare")
    assert r.status_code == 202
    assert r.json()["status"] == "ready"


def test_prepare_ws_reports_ready(client, prepared_model):
    url = f"{API}/models/{prepared_model}/floors/{TEST_FLOOR}/prepare/ws"
    with client.websocket_connect(url) as ws:
        frame = ws.receive_json()
        assert frame["status"] == "ready"
        assert frame["pct"] == 100
