"""Shared best-effort eventbus transport for metric scripts."""

from __future__ import annotations

import json
import urllib.request

DEFAULT_EVENTBUS = "http://127.0.0.1:28800"


def emit_metric(
    uri: str,
    actor: str,
    payload: dict,
    *,
    eventbus: str = DEFAULT_EVENTBUS,
) -> None:
    """Emit a metric envelope without making reporting depend on the eventbus."""
    body = json.dumps({"uri": uri, "actor": actor, "payload": payload}).encode()
    request = urllib.request.Request(
        f"{eventbus.rstrip('/')}/emit",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=3).read()
    except Exception:
        pass
