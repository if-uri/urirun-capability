"""The HTTP/OpenAPI surface is language-neutral: any stack drives the same
capabilities with the same typed contracts. Here urllib stands in for 'any
HTTP client' (curl/JS/Go/an OpenAPI-generated client)."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry  # noqa: E402
from serve import make_handler, to_openapi  # noqa: E402


def _echo_reg() -> Registry:
    r = Registry()
    r.add(Capability(
        uri="demo://local/echo/query/text", effect="query",
        input={"type": "object", "required": ["text"],
               "properties": {"text": {"type": "string"}}},
        output={"type": "object", "required": ["echoed"],
                "properties": {"echoed": {"type": "string"}}},
        adapter="python", config={"fn": lambda text: {"echoed": text}}))
    return r


def _post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)


def test_openapi_is_generated_from_the_registry():
    spec = to_openapi(_echo_reg())
    assert spec["openapi"].startswith("3.")
    op = list(spec["paths"].values())[0]["post"]
    assert op["x-effect"] == "query" and op["x-capability-id"].startswith("cap-")
    # request/response bodies ARE the capability's typed schemas
    assert op["requestBody"]["content"]["application/json"]["schema"]["required"] == ["text"]


def test_any_http_client_can_dispatch_and_gets_typed_validation():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(_echo_reg()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    time.sleep(0.2)
    try:
        base = f"http://127.0.0.1:{port}"
        assert _get(base + "/health")["capabilities"] == 1
        code, ok = _post(base + "/dispatch",
                         {"uri": "demo://local/echo/query/text", "payload": {"text": "x"}})
        assert code == 200 and ok["result"] == {"echoed": "x"} and "ms" in ok
        # typed contract enforced regardless of client language
        code, bad = _post(base + "/dispatch",
                          {"uri": "demo://local/echo/query/text", "payload": {"nope": 1}})
        assert code == 422 and bad["error"]["category"] == "INVALID_ARGUMENT"
    finally:
        srv.shutdown()
