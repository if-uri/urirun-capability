"""Drive the LIVE twin node (pc1) through the shrunk Capability core.

Proves the new model is a migration path, not a rewrite: it dispatches a real
kvm capability to the running urirun node, validates the node's output against a
contract, and emits events by construction.

Gated: URIRUN_CAP_LIVE=1 (needs the twin's pc1 node on 127.0.0.1:28765).
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry, Events, dispatch  # noqa: E402

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")

pytestmark = pytest.mark.skipif(
    os.environ.get("URIRUN_CAP_LIVE", "") != "1",
    reason="needs the live twin node (URIRUN_CAP_LIVE=1)")


def _node_up() -> bool:
    try:
        urllib.request.urlopen(f"{NODE}/health", timeout=3)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def registry():
    if not _node_up():
        pytest.skip("twin pc1 node not running")
    reg = Registry()
    # a REAL capability: screen capture on the live node, with an OUTPUT contract
    # (which v2 bindings usually omit — closing that gap catches backend drift)
    reg.add(Capability(
        uri="kvm://pc1/screen/query/capture",
        effect="query",
        input={"type": "object", "properties": {"base64": {"type": "boolean"}}},
        output={"type": "object", "required": ["ok", "backend"],
                "properties": {"ok": {"type": "boolean"}, "backend": {"type": "string"}}},
        errors=("UNAVAILABLE",),
        adapter="http-node",
        config={"node": NODE, "remoteUri": "kvm://host/screen/query/capture"},
    ))
    return reg


def test_new_core_drives_live_node_and_validates_output(registry):
    ev = Events()
    out = dispatch(registry, "kvm://pc1/screen/query/capture", {"base64": False}, events=ev)
    assert out["ok"], out.get("error")
    # the node's real output conformed to our contract (ok + backend present)
    assert out["result"].get("ok") is True
    assert isinstance(out["result"].get("backend"), str)
    # events emitted by construction
    uris = [e["uri"] for e in ev.log]
    assert "run://call/command/start" in uris and "run://call/command/done" in uris
    # content-addressed identity is stable
    assert out["capId"].startswith("cap-")


def test_contract_catches_a_wrong_output_shape(registry):
    # tighten the contract to demand a field the node does NOT return -> the core
    # catches the mismatch instead of trusting the backend
    reg = Registry()
    reg.add(Capability(
        uri="kvm://pc1/screen/query/strict", effect="query",
        output={"type": "object", "required": ["nonexistent_field"]},
        adapter="http-node",
        config={"node": NODE, "remoteUri": "kvm://host/screen/query/capture"}))
    out = dispatch(reg, "kvm://pc1/screen/query/strict", {})
    assert not out["ok"] and out["error"]["category"] == "CONTRACT_VIOLATION"
