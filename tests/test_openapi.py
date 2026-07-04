"""OpenAPI is a first-class contract source — no per-capability package needed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability import Capability, Registry  # noqa: E402
from openapi import to_openapi, from_openapi  # noqa: E402


def _reg() -> Registry:
    r = Registry()
    r.add(Capability(
        uri="demo://local/echo/query/text", effect="query",
        input={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
        output={"type": "object", "required": ["echoed"], "properties": {"echoed": {"type": "string"}}},
        adapter="python", config={"fn": lambda text: {"echoed": text}}))
    return r


def test_roundtrip_capability_to_openapi_and_back():
    reg = _reg()
    spec = to_openapi(reg)
    back = from_openapi(spec)
    orig = reg.get("demo://local/echo/query/text")
    got = back.get("demo://local/echo/query/text")
    assert got is not None, "capability lost in the round-trip"
    # the contract essence survives: effect + input + output schemas
    assert got.effect == orig.effect
    assert got.input == orig.input
    assert got.output == orig.output


def test_external_openapi_becomes_capabilities():
    # a hand-written external OpenAPI doc (not ours) imports cleanly
    external = {
        "openapi": "3.0.3", "info": {"title": "weather", "version": "1"},
        "paths": {
            "/forecast": {"get": {
                "operationId": "forecast",
                "responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "required": ["tempC"],
                               "properties": {"tempC": {"type": "number"}}}}}}}}},
            "/alerts": {"post": {
                "operationId": "alerts_create",
                "requestBody": {"content": {"application/json": {
                    "schema": {"type": "object", "required": ["msg"]}}}},
                "responses": {"201": {"content": {"application/json": {
                    "schema": {"type": "object"}}}}}}},
        },
    }
    reg = from_openapi(external, scheme="weather")
    caps = {c.uri: c for c in reg._caps.values()}
    assert len(caps) == 2
    # GET -> query, POST -> command (effect inferred from method)
    q = [c for c in caps.values() if c.effect == "query"]
    cmd = [c for c in caps.values() if c.effect == "command"]
    assert len(q) == 1 and len(cmd) == 1
    # typed output schema carried over
    assert q[0].output.get("required") == ["tempC"]
    # each imported capability is content-addressed like any other
    assert all(c.id().startswith("cap-") for c in caps.values())
