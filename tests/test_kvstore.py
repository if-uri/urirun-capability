"""The real urirun-contract-kvstore contract converts to Capabilities and works."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Events, dispatch  # noqa: E402
from kvstore import load_kvstore  # noqa: E402
from openapi import to_openapi  # noqa: E402

CONTRACTS = Path("/home/tom/github/if-uri/urirun-contract-kvstore/contracts.json")

pytestmark = pytest.mark.skipif(not CONTRACTS.exists(),
                                reason="urirun-contract-kvstore not present")


def test_real_contract_json_becomes_working_capabilities():
    reg = load_kvstore(CONTRACTS)
    assert len(reg._caps) == 2
    set_cap = reg.get("kv://host/kv/command/set")
    get_cap = reg.get("kv://host/kv/query/get")
    assert set_cap.effect == "command" and get_cap.effect == "query"
    # examples survived from contracts.json (conformance data)
    assert get_cap.examples and set_cap.examples
    # round-trip set -> get through the shared core
    ev = Events()
    s = dispatch(reg, "kv://host/kv/command/set", {"key": "g", "value": "hello"}, events=ev)
    assert s["ok"] and s["result"]["stored"] is True
    g = dispatch(reg, "kv://host/kv/query/get", {"key": "g"}, events=ev)
    assert g["ok"] and g["result"]["value"] == "hello" and g["result"]["found"] is True


def test_input_contract_is_enforced_on_the_adopted_contract():
    reg = load_kvstore(CONTRACTS)
    bad = dispatch(reg, "kv://host/kv/command/set", {"key": "x"})  # missing 'value'
    assert not bad["ok"] and bad["error"]["category"] == "INVALID_ARGUMENT"


def test_openapi_generated_from_the_real_contract():
    reg = load_kvstore(CONTRACTS)
    spec = to_openapi(reg)
    assert len(spec["paths"]) == 2
    assert any(op["post"]["x-effect"] in ("query", "command") for op in spec["paths"].values())
