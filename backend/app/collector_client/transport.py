from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any

HTTP_TIMEOUT_SECONDS = 60


def _get_json(server_url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(_url(server_url, path), timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))

def _post_json(server_url: str, path: str, payload: dict[str, object]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _url(server_url, path),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"http_error:{exc.code}") from exc

def _url(server_url: str, path: str) -> str:
    return server_url.rstrip("/") + path

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
