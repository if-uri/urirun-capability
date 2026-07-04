"""Examples do triple duty: valid payloads, deterministic planning, and — the
decisive win — catching regressions that schema-only checks miss."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry, _validate  # noqa: E402
from planner import from_examples, synth_from_schema, plan, plan_and_run  # noqa: E402


def _kv() -> Registry:
    r = Registry()
    r.add(Capability(
        uri="kv://host/kv/query/get", effect="query",
        input={"type": "object", "required": ["key"], "properties": {"key": {"type": "string"}}},
        output={"type": "object", "required": ["value"], "properties": {"value": {"type": "string"}}},
        examples=({"input": {"key": "greeting"}, "output": {"value": "hello"}},),
        adapter="python",
        config={"fn": lambda key: {"value": "hello"}}))       # correct handler
    return r


def test_example_payload_is_contract_valid():
    reg = _kv(); cap = reg.get("kv://host/kv/query/get")
    p = from_examples(cap)
    assert p == {"key": "greeting"} and _validate(cap.input, p) is None


def test_schema_synthesis_is_structurally_valid_too():
    # honesty: without examples you CAN synthesize a type-valid payload
    cap = _kv().get("kv://host/kv/query/get")
    p = synth_from_schema(cap.input)
    assert _validate(cap.input, p) is None      # valid by type
    assert p != from_examples(cap)              # but not the meaningful value


def test_plan_is_deterministic_and_offline():
    reg = _kv()
    a = plan(reg, "get greeting value")
    b = plan(reg, "get greeting value")
    assert a == b and a["ok"] and a["source"] == "examples"   # same plan, no LLM


def test_examples_catch_a_regression_that_schema_only_misses():
    # correct handler -> golden pair conforms
    reg = _kv()
    ok = plan_and_run(reg, reg.get("kv://host/kv/query/get"), use_examples=True)
    assert ok["conformant"]

    # break the handler (returns the wrong value) -> a real regression
    broken = Registry()
    broken.add(Capability(**{**reg.get("kv://host/kv/query/get").__dict__,
                             "config": {"fn": lambda key: {"value": "WRONG"}}}))
    cap = broken.get("kv://host/kv/query/get")
    # WITH examples: the golden output mismatch is CAUGHT
    with_ex = plan_and_run(broken, cap, use_examples=True)
    assert with_ex["ok"] and not with_ex["conformant"], "examples must catch the drift"
    # WITHOUT examples: it just 'runs fine' — the drift is invisible
    without = plan_and_run(broken, cap, use_examples=False)
    assert without["ok"] and without["conformant"], "schema-only check cannot see behaviour drift"
