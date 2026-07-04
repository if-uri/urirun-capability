"""The URI-process "server" is language-independent.

One typed capability contract (sys://host/os/query/info) is satisfied by nodes
written in DIFFERENT languages (JavaScript + Go). The same Python client drives
all of them uniformly through the Capability core, validating every node's
output against the SAME contract — and negotiates by reading what each node
advertises it can satisfy.

Gated: URIRUN_CAP_POLYGLOT=1 (needs node and go on PATH).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry, Events, dispatch  # noqa: E402

NODES = Path(__file__).resolve().parents[1] / "nodes"

pytestmark = pytest.mark.skipif(
    os.environ.get("URIRUN_CAP_POLYGLOT", "") != "1",
    reason="needs node + go (URIRUN_CAP_POLYGLOT=1)")

# the ONE contract every node must satisfy, regardless of language
OS_INFO = dict(
    uri="sys://host/os/query/info", effect="query",
    input={"type": "object", "properties": {}},
    output={"type": "object", "required": ["ok", "os", "arch", "lang"],
            "properties": {"ok": {"type": "boolean"}, "os": {"type": "string"},
                           "arch": {"type": "string"}, "lang": {"type": "string"}}},
    adapter="http-node")


def _wait(url, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2); return True
        except Exception:
            time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def nodes():
    if not (shutil.which("node") and shutil.which("go")):
        pytest.skip("node/go not available")
    procs = []
    # JS node
    procs.append(subprocess.Popen(["node", str(NODES / "node.js")],
                                  env={**os.environ, "PORT": "8871"}))
    # Go node (compile once, then run the binary — fast, reliable start)
    gobin = Path("/tmp/cap-node-go")
    subprocess.run(["go", "build", "-o", str(gobin), str(NODES / "node.go")], check=True, timeout=90)
    procs.append(subprocess.Popen([str(gobin)], env={**os.environ, "PORT": "8872"}))
    ok = _wait("http://127.0.0.1:8871/health") and _wait("http://127.0.0.1:8872/health")
    if not ok:
        for p in procs:
            p.terminate()
        pytest.skip("nodes did not come up")
    yield {"javascript": "http://127.0.0.1:8871", "go": "http://127.0.0.1:8872"}
    for p in procs:
        p.terminate()


def _advertised(node_url) -> list[dict]:
    with urllib.request.urlopen(f"{node_url}/capabilities", timeout=5) as r:
        return json.load(r)["capabilities"]


def test_every_language_advertises_the_same_contract(nodes):
    # negotiation: each node says which contract it can satisfy (+ its backend)
    for lang, url in nodes.items():
        adv = _advertised(url)
        assert any(c["uri"] == "sys://host/os/query/info" for c in adv), f"{lang} missing contract"
        assert adv[0]["backend"].startswith((lang[:2], "node", "go")), adv[0]["backend"]


def test_one_client_drives_every_language_with_one_contract(nodes):
    langs_seen = set()
    for lang, url in nodes.items():
        reg = Registry()
        reg.add(Capability(**{**OS_INFO, "config": {"node": url, "protocol": "capability"}}))
        ev = Events()
        out = dispatch(reg, "sys://host/os/query/info", {}, events=ev)
        assert out["ok"], f"{lang}: {out.get('error')}"
        # the node's real output conformed to the SHARED contract
        r = out["result"]
        assert r["ok"] is True and isinstance(r["os"], str) and isinstance(r["arch"], str)
        # and it was genuinely served by that language
        assert r["lang"] == lang, f"expected {lang}, got {r['lang']}"
        langs_seen.add(r["lang"])
        # events emitted by construction, same for every language
        assert "run://call/command/done" in [e["uri"] for e in ev.log]
    assert langs_seen == {"javascript", "go"}, langs_seen


def test_contract_gate_is_enforced_across_languages(nodes):
    # tighten the contract to demand a field no node returns -> the client catches
    # the mismatch, uniformly, regardless of the server's language
    for url in nodes.values():
        reg = Registry()
        reg.add(Capability(uri="sys://host/os/query/strict", effect="query",
                           output={"type": "object", "required": ["not_there"]},
                           adapter="http-node",
                           config={"node": url, "protocol": "capability",
                                   "remoteUri": "sys://host/os/query/info"}))
        out = dispatch(reg, "sys://host/os/query/strict", {})
        assert not out["ok"] and out["error"]["category"] == "CONTRACT_VIOLATION"
