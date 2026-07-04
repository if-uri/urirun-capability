"""Prove the Capability core invariants — the things current urirun leaves implicit."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry, Events, dispatch, check_examples  # noqa: E402


def _echo() -> Capability:
    return Capability(
        uri="demo://local/echo/query/text",
        effect="query", idempotent=True,
        input={"type": "object", "required": ["text"],
               "properties": {"text": {"type": "string"}}, "additionalProperties": False},
        output={"type": "object", "required": ["echoed"],
                "properties": {"echoed": {"type": "string"}}},
        errors=("INVALID_ARGUMENT",),
        examples=({"input": {"text": "hi"}, "output": {"echoed": "hi"}},),
        adapter="python", config={"fn": lambda text: {"echoed": text}},
    )


def _delete() -> Capability:
    return Capability(
        uri="demo://local/file/command/delete",
        effect="command", reversible=False,
        input={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
        output={"type": "object", "properties": {"deleted": {"type": "boolean"}}},
        errors=("PERMISSION_DENIED", "NOT_FOUND"),
        adapter="python", config={"fn": lambda path: {"deleted": True}},
    )


def test_dispatch_emits_events_by_construction():
    reg = Registry(); reg.add(_echo())
    ev = Events()
    out = dispatch(reg, "demo://local/echo/query/text", {"text": "hi"}, events=ev)
    assert out["ok"] and out["result"] == {"echoed": "hi"}
    uris = [e["uri"] for e in ev.log]
    assert any(u.startswith("run://") and "/command/start" in u for u in uris)
    assert any(u.startswith("run://") and "/command/done" in u for u in uris)


def test_effect_is_typed_not_parsed_from_url():
    # a command capability whose URL says /command/ AND a typed effect field agree,
    # but the GATE reads the field — so safety is deterministic
    reg = Registry(); reg.add(_delete())
    blocked = dispatch(reg, "demo://local/file/command/delete", {"path": "/x"}, allow_commands=False)
    assert not blocked["ok"]
    assert blocked["error"]["category"] == "PERMISSION_DENIED"
    allowed = dispatch(reg, "demo://local/file/command/delete", {"path": "/x"}, allow_commands=True)
    assert allowed["ok"]


def test_bad_input_is_a_typed_error_event():
    reg = Registry(); reg.add(_echo())
    ev = Events()
    out = dispatch(reg, "demo://local/echo/query/text", {"wrong": 1}, events=ev)
    assert not out["ok"] and out["error"]["category"] == "INVALID_ARGUMENT"
    assert ev.by_scheme("error"), "an error:// event must be emitted"


def test_output_contract_violation_is_caught():
    # backend returns the wrong shape -> the contract catches it (not trusted)
    bad = Capability(
        uri="demo://local/broken/query/x", effect="query",
        output={"type": "object", "required": ["echoed"], "properties": {"echoed": {"type": "string"}}},
        adapter="python", config={"fn": lambda: {"WRONG": "shape"}})
    reg = Registry(); reg.add(bad)
    out = dispatch(reg, "demo://local/broken/query/x", {})
    assert not out["ok"] and out["error"]["category"] == "CONTRACT_VIOLATION"


def test_content_addressed_identity_and_drift():
    a = _echo()
    same = _echo()
    assert a.id() == same.id(), "same contract -> same id"
    # change the contract -> id changes (drift is visible)
    changed = Capability(**{**a.__dict__, "output": {"type": "object", "required": ["result"]}})
    assert changed.id() != a.id()

    reg = Registry(); reg.add(a)
    lock = reg.lock()
    assert not reg.drift(lock), "no drift against its own lock"
    reg.add(changed)  # same uri, new contract
    drift = reg.drift(lock)
    assert drift and drift[0]["issue"] == "changed"


def test_examples_are_conformance_tests():
    reg = Registry(); cap = _echo(); reg.add(cap)
    rep = check_examples(reg, cap)
    assert rep["passed"] == rep["total"] == 1


def test_whole_core_is_small():
    # the point: the process model + its conformance gates (examples, reversibility) are
    # a few hundred lines, not tens of thousands (~26k in the original runtime)
    core = (Path(__file__).resolve().parents[1] / "capability.py").read_text().count("\n")
    assert core < 400, f"core grew to {core} lines"
