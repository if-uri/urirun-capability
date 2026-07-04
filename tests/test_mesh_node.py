"""Wire a descriptor-only connector into the mesh: serve it as a live HTTP node
(serve.py) and drive it from a separate Capability client over http-node — a
language-neutral capability node, no per-connector server code."""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry, dispatch  # noqa: E402
from serve import make_handler  # noqa: E402
from poc_connector_hash import hash_connector  # noqa: E402


def _serve(reg):
    srv = HTTPServer(("127.0.0.1", 0), make_handler(reg))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_descriptor_connector_runs_as_a_live_node_over_http():
    srv, node = _serve(hash_connector())
    try:
        # a client capability points at the node; the client never imports the connector
        client = Registry()
        client.add(Capability(uri="hash://mesh/text/query/sha256", effect="query",
                              input={"type": "object", "required": ["text"]},
                              output={"type": "object", "required": ["hex"]},
                              adapter="http-node",
                              config={"node": node, "protocol": "capability",
                                      "remoteUri": "hash://host/text/query/sha256"}))
        out = dispatch(client, "hash://mesh/text/query/sha256", {"text": "hello"})
        assert out["ok"]
        assert out["result"]["hex"] == \
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    finally:
        srv.shutdown()


def test_node_serves_capabilities_and_openapi_for_discovery():
    srv, node = _serve(hash_connector())
    try:
        caps = json.load(urllib.request.urlopen(f"{node}/capabilities", timeout=5))["capabilities"]
        assert len(caps) == 4                              # discoverable descriptors
        assert all("config" not in c for c in caps)        # handler fn never exposed
        api = json.load(urllib.request.urlopen(f"{node}/openapi.json", timeout=5))
        assert len(api["paths"]) == 4                      # OpenAPI served straight from descriptors
    finally:
        srv.shutdown()
