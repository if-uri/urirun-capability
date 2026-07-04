"""Multi-step planner: a goal -> an ordered flow of capabilities, with outputs
wired into later inputs, and LLM-free automatic rollback via the `inverse` field.

This is the payoff of typed, effect-classified, reversible contracts: the runtime
can compose AND undo flows deterministically — no LLM, no hand-written rollback.

  run_flow(registry, steps)   -> run an ordered flow, threading outputs
  plan_undo(registry, ran)    -> from a reversible command that ran, build its
                                 inverse step (wiring the output into the inverse input)
  undo_flow(registry, results)-> compensate a completed flow: every reversible step,
                                 newest first, via its inverse (a saga rollback)
  run_saga(registry, steps)   -> run a flow that AUTO-compensates on failure —
                                 if a step fails, already-done reversible steps are undone
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


def undo_flow(registry: Registry, results: list[dict], *, events: Events | None = None,
              actor: str = "planner") -> dict:
    """Compensate a completed flow: walk results newest-first, and for every
    reversible step run its inverse. Non-reversible steps (e.g. a sent mail) are
    reported as un-compensable — the honest limit of any rollback."""
    events = events or Events()
    events.emit("saga://tx/command/rollback-start", actor=actor, steps=len(results))
    undone, skipped = [], []
    for res in reversed(results):
        u = plan_undo(registry, res)
        if not u:
            skipped.append(res.get("uri"))
            continue
        out = dispatch(registry, u["uri"], u["payload"], events=events, actor=actor)
        (undone if out.get("ok") else skipped).append(u["uri"])
    events.emit("saga://tx/command/rollback-done", actor=actor,
                undone=len(undone), skipped=len(skipped))
    return {"undone": undone, "irreversible": skipped, "events": events.log}


def run_saga(registry: Registry, steps: list[dict], *, events: Events | None = None,
             actor: str = "planner") -> dict:
    """Run a flow as a saga: if any step fails, automatically compensate every
    already-completed reversible step (newest first). All-or-nothing for the
    reversible part — no half-applied transaction left behind."""
    events = events or Events()
    ctx: list[dict] = []
    events.emit("saga://tx/command/start", actor=actor, steps=len(steps))
    for i, step in enumerate(steps):
        payload = dict(step.get("payload", {}))
        for field, path in (step.get("wire") or {}).items():
            payload[field] = _dig(ctx, path)
        out = dispatch(registry, step["uri"], payload, events=events, actor=actor)
        if not out.get("ok"):
            events.emit("saga://tx/command/compensate", actor=actor, failedAt=i, stepUri=step["uri"])
            comp = undo_flow(registry, ctx, events=events, actor=actor)
            return {"ok": False, "at": i, "results": ctx, "compensated": comp["undone"],
                    "irreversible": comp["irreversible"], "events": events.log}
        ctx.append(out)
    events.emit("saga://tx/command/commit", actor=actor, steps=len(steps))
    return {"ok": True, "results": ctx, "events": events.log}


def _dig(ctx: list[dict], path: str):
    parts = path.split(".")
    cur = ctx[int(parts[0])]
    for p in parts[1:]:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def plan_undo(registry: Registry, ran: dict, *, node_scheme: str = "") -> dict | None:
    """Build the inverse step for a reversible command that ran. Prefers the
    concrete `inverse` the runtime returned (e.g. {"uri": "kvm://host/proc/command/kill",
    "args": {"pid": 34727}}); falls back to the contract's static inverse + field wiring.
    Returns {uri, payload, remoteUri?} or None if not reversible."""
    result = ran.get("result", {})
    uri = ran.get("uri")
    # 1) runtime-provided concrete inverse (has real args like a pid)
    rt = result.get("inverse") if isinstance(result, dict) else None
    if isinstance(rt, dict) and (rt.get("uri") or rt.get("path")):
        remote = rt.get("uri") or rt.get("path")
        # map the node-local remote uri to a registry uri if the caller registered one
        local = _match_local(registry, remote, node_scheme, uri)
        return {"uri": local or remote, "payload": dict(rt.get("args", {})), "remoteUri": remote}
    # 2) static inverse from the contract + field wiring
    cap = registry.get(uri)
    if not cap or not cap.reversible or not cap.inverse:
        return None
    inv = registry.get(cap.inverse)
    if not inv:
        return None
    payload = {}
    req = (inv.input or {}).get("required", list((inv.input or {}).get("properties") or {}))
    for field in req:
        if field in result:
            payload[field] = result[field]
    return {"uri": cap.inverse, "payload": payload}


def _match_local(registry: Registry, remote: str, scheme: str, origin: str) -> str | None:
    """Resolve a runtime-provided inverse target to a registered capability URI:
    first by an exact remoteUri match (http-node), then by route suffix (a bare
    route like 'file/command/restore' -> 'fs://host/file/command/restore')."""
    for u, cap in registry._caps.items():
        if cap.config.get("remoteUri") == remote:
            return u
    route = remote.split("://", 1)[-1]                 # strip any scheme
    route = route.split("/", 1)[-1] if "/" in route else route  # drop authority if present
    for u in registry._caps:
        if u.split("://", 1)[-1].split("/", 1)[-1] == route or u.endswith("/" + route):
            return u
    return None
