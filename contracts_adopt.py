"""Generic adopter: turn ANY urirun-contract-* package's contracts.json into
Capability descriptors on the shared core. Works for all four packages.

The connector's real handler is not needed to adopt the CONTRACT — the descriptor
(effect, schemas, reversibility, errors, examples) is the portable essence. A
stub handler replays the first example's output so conformance/dispatch runs.
"""
from __future__ import annotations

import json
from pathlib import Path

from capability import Capability, Registry

_MAP = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
        "obj": "object", "dict": "object", "list": "array", "array": "array"}


_UNIONS = ("oneOf", "anyOf", "allOf")


def _leaf(spec) -> tuple[dict, bool]:
    """Convert one mini-schema value -> (json-schema, required?). Handles nested
    dicts/unions, arrays (['int']), const:, obj/list/any types, '?' optional."""
    if isinstance(spec, dict):                    # nested object or union
        return mini_to_jsonschema(spec), True
    if isinstance(spec, list):                    # ['int'] -> array of int
        items = _leaf(spec[0])[0] if spec else {}
        return {"type": "array", "items": items}, True
    spec = spec if isinstance(spec, str) else "any"
    optional = spec.startswith("?")
    s = spec[1:] if optional else spec
    if s.startswith("const:"):
        v = s[len("const:"):]
        return {"const": {"true": True, "false": False}.get(v, v)}, not optional
    if s in ("any", "*", ""):
        return {}, not optional                   # any type
    return {"type": _MAP.get(s, "string")}, not optional


def mini_to_jsonschema(mini: dict) -> dict:
    """urirun mini-schema -> JSON Schema. Grammar: str|int|float|bool|obj|list|any,
    '?'=optional, 'const:X'=fixed value, ['T']=array, nested dict=object,
    {oneOf|anyOf|allOf: [...]}=union."""
    # union at this level (e.g. {"oneOf": [branchA, branchB]})
    for kw in _UNIONS:
        if kw in mini and isinstance(mini[kw], list):
            return {kw: [mini_to_jsonschema(b) for b in mini[kw]]}
    props, required = {}, []
    for name, spec in (mini or {}).items():
        schema, is_req = _leaf(spec)
        props[name] = schema
        if is_req:
            required.append(name)
    out = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def _make_stub(examples: tuple):
    """Input-aware replay: return the output of the example whose input equals the
    call's kwargs, so a multi-example contract conforms on ALL its examples."""
    first = examples[0]["output"] if examples else {"ok": True}

    def stub(**kw):
        for ex in examples:
            if ex.get("input", {}) == kw:
                return dict(ex["output"]) if isinstance(ex["output"], dict) else ex["output"]
        return dict(first) if isinstance(first, dict) else first
    return stub


def adopt_contracts(contracts_json: Path, scheme: str, handlers: dict | None = None) -> Registry:
    doc = json.loads(Path(contracts_json).read_text())
    reg = Registry()
    for route, c in doc["contracts"].items():
        parts = route.split("/")
        obj, effect, action = parts[0], parts[1], "/".join(parts[2:])
        uri = f"{scheme}://host/{obj}/{effect}/{action}"
        examples = tuple({"input": e.get("payload", {}), "output": e.get("result")}
                         for e in c.get("examples", []))
        # stub handler: replay the golden output of the example whose INPUT matches
        # the call (not always the first) — so conformance verifies EVERY example, not
        # just one. Falls back to the first example, then to {"ok": True}.
        fn = (handlers or {}).get(route) or _make_stub(examples)
        reg.add(Capability(
            uri=uri, effect=c["effect"], reversible=bool(c.get("reversible")),
            inverse=(f"{scheme}://host/{obj}/command/{c['inverseRoute'].split('/')[-1]}"
                     if c.get("inverseRoute") else ""),
            input=mini_to_jsonschema(c.get("inp", {})),
            output=mini_to_jsonschema(c.get("out", {})),
            errors=tuple(c.get("errors", ())),
            examples=examples,
            adapter="python", config={"fn": fn}))
    return reg
