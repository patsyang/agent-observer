from __future__ import annotations

import hashlib
import json
import socket
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
        if exc.code in {408, 504}:
            raise TimeoutError(f"http_timeout:{exc.code}") from exc
        raise ValueError(f"http_error:{exc.code}") from exc

def _url(server_url: str, path: str) -> str:
    return server_url.rstrip("/") + path

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text or "http_error:504" in text or "http_error:408" in text
