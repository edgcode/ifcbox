"""Logical blob keys (storage-backend agnostic). See plans/spec-deploy.md §3.2."""

from __future__ import annotations


def model_dir(model_id: str) -> str:
    return f"models/{model_id}"


def model_ifc(model_id: str) -> str:
    return f"models/{model_id}/original.ifc"


def model_meta(model_id: str) -> str:
    return f"models/{model_id}/meta.json"


def floor_dir(model_id: str, n: int) -> str:
    return f"models/{model_id}/floors/{n}"


def floor_prepared(model_id: str, n: int) -> str:
    return f"models/{model_id}/floors/{n}/prepared.npz"


def floor_shell(model_id: str, n: int) -> str:
    return f"models/{model_id}/floors/{n}/shell.glb"


def floor_walls(model_id: str, n: int) -> str:
    return f"models/{model_id}/floors/{n}/walls.json"


def floor_rooms(model_id: str, n: int) -> str:
    return f"models/{model_id}/floors/{n}/rooms.png"


def route_dir(route_id: str) -> str:
    return f"routes/{route_id}"


def route_request(route_id: str) -> str:
    return f"routes/{route_id}/request.json"


def route_result(route_id: str) -> str:
    return f"routes/{route_id}/route.json"


def route_mesh(route_id: str) -> str:
    return f"routes/{route_id}/pipe.glb"
