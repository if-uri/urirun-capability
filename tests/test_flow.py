"""Multi-step flows with wiring + LLM-free automatic rollback via `inverse`."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Registry, Capability, Events, dispatch  # noqa: E402
from flow import run_flow, plan_undo  # noqa: E402
from filepair import load_filepair, FILES  # noqa: E402

FP = Path("/home/tom/github/if-uri/urirun-contract-filepair/contracts.json")


def _kv():
    store = {}
    r = Registry()
    r.add(Capability(uri="kv://host/kv/command/set", effect="command",
                     input={"type": "object", "required": ["key", "value"],
                            "properties": {"key": {"type": "string"}, "value": {"type": "string"}}},
                     output={"type": "object", "properties": {"key": {"type": "string"}}},
                     adapter="python",
                     config={"fn": lambda key, value: (store.__setitem__(key, value), {"key": key})[1]}))
    r.add(Capability(uri="kv://host/kv/query/get", effect="query",
                     input={"type": "object", "required": ["key"],
                            "properties": {"key": {"type": "string"}}},
                     output={"type": "object", "properties": {"value": {"type": "string"}}},
                     adapter="python",
                     config={"fn": lambda key: {"value": store.get(key)}}))
    return r


def test_multistep_flow_wires_output_into_next_input():
    reg = _kv()
    # goal: store greeting, then read it back — the set's output key wires into get
    out = run_flow(reg, [
        {"uri": "kv://host/kv/command/set", "payload": {"key": "greeting", "value": "hello"}},
        {"uri": "kv://host/kv/query/get", "wire": {"key": "0.result.key"}},
    ])
    assert out["ok"]
    assert out["results"][1]["result"]["value"] == "hello"
    uris = [e["uri"] for e in out["events"]]
    assert "flow://plan/command/start" in uris and "flow://plan/command/done" in uris


@pytest.mark.skipif(not FP.exists(), reason="urirun-contract-filepair not present")
def test_reversible_command_auto_rolls_back_via_inverse():
    reg = load_filepair()
    FILES.clear()
    FILES["/notes.txt"] = "important content"

    # run the reversible command: snapshot + delete
    ran = run_flow(reg, [{"uri": "fs://host/file/command/snapshot-delete",
                          "payload": {"path": "/notes.txt"}}])
    assert ran["ok"]
    assert "/notes.txt" not in FILES, "file should be deleted by the command"

    # the runtime AUTO-BUILDS the undo from the contract's inverse — no LLM, no
    # hand-written rollback
    undo = plan_undo(reg, ran["results"][0])
    assert undo is not None and undo["uri"] == "fs://host/file/command/restore"

    # run the undo -> the file is restored to its exact prior content
    back = run_flow(reg, [undo])
    assert back["ok"]
    assert FILES.get("/notes.txt") == "important content", "auto-rollback must restore the file"


@pytest.mark.skipif(not FP.exists(), reason="urirun-contract-filepair not present")
def test_non_reversible_has_no_auto_undo():
    reg = _kv()
    ran = run_flow(reg, [{"uri": "kv://host/kv/query/get", "payload": {"key": "x"}}])
    # a query is not a reversible command -> no undo plan
    assert plan_undo(reg, ran["results"][0]) is None
