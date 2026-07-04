"""Multi-step planner: a goal -> an ordered flow of capabilities, with outputs
wired into later inputs, and LLM-free automatic rollback via the `inverse` field.

This is the payoff of typed, effect-classified, reversible contracts: the runtime
can compose AND undo flows deterministically — no LLM, no hand-written rollback.

  run_flow(registry, steps)   -> run an ordered flow, threading outputs
  plan_undo(registry, ran)    -> from a reversible command that ran, build its
                                 inverse step (wiring the output into the inverse input)
"""
from __future__ import annotations

import time

from capability import Registry, Events, dispatch


def run_flow(registry: Registry, steps: list[dict], *, events: Events | None = None,
             actor: str = "planner") -> dict:
    """Each step: {uri, payload?, wire?}. `wire` maps an input field to a dotted
    path in a prior step's result: {"snapshot": "0.result.snapshot"}."""
    events = events or Events()
    ctx: list[dict] = []
    t0 = time.time()
    events.emit("flow://plan/command/start", actor=actor, steps=len(steps))
    for i, step in enumerate(steps):
        payload = dict(step.get("payload", {}))
        for field, path in (step.get("wire") or {}).items():
            payload[field] = _dig(ctx, path)
        out = dispatch(registry, step["uri"], payload, events=events, actor=actor)
        ctx.append(out)
        if not out.get("ok"):
            events.emit("flow://plan/command/abort", actor=actor, at=i, stepUri=step["uri"])
            return {"ok": False, "at": i, "results": ctx, "events": events.log}
    ms = round((time.time() - t0) * 1000, 2)
    events.emit("flow://plan/command/done", actor=actor, steps=len(steps), ms=ms)
    return {"ok": True, "results": ctx, "ms": ms, "events": events.log}


def _dig(ctx: list[dict], path: str):
    parts = path.split(".")
    cur = ctx[int(parts[0])]
    for p in parts[1:]:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def plan_undo(registry: Registry, ran: dict) -> dict | None:
    """Given a reversible command that ran (ran = the run_flow result of ONE step),
    build the inverse step deterministically from the contract's `inverse` + result.
    Returns {uri, payload} or None if not reversible."""
    result = ran.get("result", {})
    uri = ran.get("uri")
    cap = registry.get(uri)
    if not cap or not cap.reversible or not cap.inverse:
        return None
    inv = registry.get(cap.inverse)
    if not inv:
        return None
    # wire the inverse input from this result: the contract's result carries the
    # payload to undo (e.g. a 'snapshot'); match by the inverse's required fields
    payload = {}
    req = (inv.input or {}).get("required", list((inv.input or {}).get("properties") or {}))
    for field in req:
        if field in result:
            payload[field] = result[field]
    return {"uri": cap.inverse, "payload": payload}
