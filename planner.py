"""Planner over the typed capability space — examples do triple duty:
conformance tests, few-shot data, AND deterministic planner seeds (no LLM).

Two ways to produce a runnable payload for a capability:
  from_examples(cap)  -> the golden input (contract-valid by construction)
  synth_from_schema(cap) -> a naive type-based guess (what you'd do without examples)

plan(registry, goal) ranks capabilities by relevance to a goal string and, if the
best has examples, returns a ready-to-run plan — deterministically, offline.
"""
from __future__ import annotations

from capability import Capability, Registry, Events, dispatch, _validate


def from_examples(cap: Capability) -> dict | None:
    return dict(cap.examples[0]["input"]) if cap.examples else None


def synth_from_schema(schema: dict) -> dict:
    """Best-effort payload from JSON Schema alone (no examples). Fills required
    fields by type; cannot know meaningful values, const branches or nested intent."""
    if not schema or schema.get("type") != "object":
        return {}
    out = {}
    props = schema.get("properties") or {}
    for name in schema.get("required", list(props)):
        s = props.get(name, {})
        if "const" in s:
            out[name] = s["const"]
        else:
            out[name] = {"string": "x", "integer": 0, "number": 0, "boolean": False,
                         "array": [], "object": {}}.get(s.get("type"), "x")
    return out


def relevance(cap: Capability, goal: str) -> int:
    g = goal.lower()
    hay = (cap.uri + " " + " ".join(str(e) for e in cap.examples)).lower()
    return sum(1 for tok in g.split() if tok in hay)


def plan(registry: Registry, goal: str, *, use_examples: bool = True) -> dict:
    ranked = sorted(registry._caps.values(), key=lambda c: relevance(c, goal), reverse=True)
    if not ranked or relevance(ranked[0], goal) == 0:
        return {"ok": False, "reason": "no matching capability"}
    cap = ranked[0]
    payload = from_examples(cap) if use_examples else synth_from_schema(cap.input)
    valid = _validate(cap.input, payload or {}) is None
    return {"ok": True, "uri": cap.uri, "payload": payload, "input_valid": valid,
            "source": "examples" if use_examples else "schema"}


def plan_and_run(registry: Registry, cap: Capability, *, use_examples: bool) -> dict:
    payload = from_examples(cap) if use_examples else synth_from_schema(cap.input)
    ev = Events()
    out = dispatch(registry, cap.uri, payload or {}, events=ev)
    # conformance: does the produced result match the golden expected output?
    expected = cap.examples[0]["output"] if (use_examples and cap.examples) else None
    conformant = out.get("ok") and (expected is None or out.get("result") == expected)
    return {"uri": cap.uri, "ok": bool(out.get("ok")), "conformant": bool(conformant),
            "error": out.get("error", {}).get("category") if not out.get("ok") else None}
