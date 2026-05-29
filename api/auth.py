"""Single shared-secret gate. Disabled when IFCBOX_APP_TOKEN is unset (local/dev).

Accepts the token via the `X-App-Token` header (HTTP) or a `token` query param
(needed for WebSockets and direct asset GETs like glTF/overlay images, which
can't set headers).
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, Query


def require_token(
    x_app_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    expected = os.environ.get("IFCBOX_APP_TOKEN")
    if not expected:
        return
    if (x_app_token or token) != expected:
        raise HTTPException(status_code=401, detail="invalid or missing app token")
