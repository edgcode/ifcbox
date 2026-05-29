"""PreparedFloor cache: in-process LRU over the on-disk .npz cache."""

from __future__ import annotations

import threading
from collections import OrderedDict

from ifcbox.engine import PreparedFloor
from api.storage import blobs
from api.storage import keys

_MAX = 4
_mem: "OrderedDict[tuple[str, int], PreparedFloor]" = OrderedDict()
_lock = threading.Lock()


def _remember(key, prep) -> None:
    _mem[key] = prep
    _mem.move_to_end(key)
    while len(_mem) > _MAX:
        _mem.popitem(last=False)


def get_prepared(model_id: str, floor: int) -> PreparedFloor | None:
    """Return a PreparedFloor from memory, else disk, else None (not prepared)."""
    key = (model_id, floor)
    with _lock:
        if key in _mem:
            _mem.move_to_end(key)
            return _mem[key]

    if not blobs.exists(keys.floor_prepared(model_id, floor)):
        return None
    d = blobs.read_dir(keys.floor_dir(model_id, floor))
    if d is None:
        return None
    prep = PreparedFloor.load(d)
    with _lock:
        _remember(key, prep)
    return prep


def put_prepared(model_id: str, floor: int, prep: PreparedFloor) -> None:
    with _lock:
        _remember((model_id, floor), prep)


def evict_model(model_id: str) -> None:
    with _lock:
        for k in [k for k in _mem if k[0] == model_id]:
            del _mem[k]
