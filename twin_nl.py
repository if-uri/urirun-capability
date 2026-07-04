"""Natural-language goal -> a flow of twin capabilities -> run on the LIVE pc1
node, with LLM-free automatic rollback via the runtime's inverse.

Ties everything together: examples seed the planner, the typed contracts classify
effect + reversibility, the http-node adapter drives the real mesh, and plan_undo
uses the concrete inverse the node returns (a pid) to undo — deterministically,
no LLM.
"""
from __future__ import annotations

import os
import re
import urllib.request

from capability import Capability, Registry, Events, dispatch
from flow import run_flow, plan_undo

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")


def twin_registry(node: str = NODE) -> Registry:
    """pc1 capabilities as descriptors (examples + PL keywords), driving the live node."""
    reg = Registry()
    reg.add(Capability(
        uri="app://pc1/desktop/command/launch", effect="command", reversible=True,
        input={"type": "object", "required": ["app"], "properties": {"app": {"type": "string"}}},
        output={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        examples=({"input": {"app": "xterm", "settle": 1},
                   "output": {"ok": True}},),
        adapter="http-node",
        config={"node": node, "remoteUri": "app://host/desktop/command/launch",
                "keywords": "otworz otwórz uruchom terminal aplikacja app okno launch"}))
    reg.add(Capability(
        uri="kvm://pc1/screen/query/capture", effect="query",
        input={"type": "object", "properties": {"base64": {"type": "boolean"}}},
        output={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
        examples=({"input": {"base64": False}, "output": {"ok": True}},),
        adapter="http-node",
        config={"node": node, "remoteUri": "kvm://host/screen/query/capture",
                "keywords": "zrzut ekran screenshot ekranu zdjecie zdjęcie"}))
    # the inverse target so an auto-rollback (kill pid) can run through the node
    reg.add(Capability(
        uri="kvm://pc1/proc/command/kill", effect="command",
        input={"type": "object", "required": ["pid"], "properties": {"pid": {"type": "integer"}}},
        adapter="http-node",
        # internal: only used for auto-rollback, never planned from a user goal
        config={"node": node, "remoteUri": "kvm://host/proc/command/kill", "internal": True}))
    return reg


def _keywords(cap: Capability) -> str:
    # match against the declared keywords + the object/action of the URI path,
    # NOT the scheme/authority (the node name appears in every uri)
    path = cap.uri.split("://", 1)[-1].split("/")
    obj_action = " ".join(path[1:]) if len(path) > 1 else ""
    return _norm(obj_action + " " + cap.config.get("keywords", ""))


_ACCENTS = str.maketrans("ąćęłńóśźżäöü", "acelnoszzaou")
_STOP = {"czy", "jak", "sie", "dla", "the", "and", "por", "kto", "gdzie", "moze"}


def _norm(s: str) -> str:
    """Lowercase + strip Polish diacritics so 'zgłoszenie' matches keyword 'zgloszenie'
    and routing is robust to how the operator types."""
    return s.lower().translate(_ACCENTS)


def plan_flow_nl(registry: Registry, goal: str) -> list[dict]:
    """Match goal tokens to capabilities and order them by where their trigger word
    first appears in the goal. Payloads come from each capability's example (seed)."""
    g = _norm(goal)
    tokens = re.findall(r"\w+", g)
    picked = []
    for cap in registry._caps.values():
        if cap.config.get("internal"):
            continue
        kw_words = set(_keywords(cap).split())
        # match WHOLE keyword words (not substrings of longer words — 'czy' must not
        # hit 'przyczyna'); allow a stem only for 5+ char keywords fully inside a token
        # (so 'sklasyfikuj' hits 'klasyfikuj'). Common stopwords never match.
        hits = [t for t in tokens if len(t) > 2 and t not in _STOP and (
            t in kw_words or any(len(w) >= 5 and w in t for w in kw_words))]
        if not hits:
            continue
        pos = min(g.index(h) for h in hits)          # first mention -> order
        payload = dict(cap.examples[0]["input"]) if cap.examples else {}
        # rank: more keyword hits = more specific match (breaks 'faktura' ties in
        # favour of the capability the goal describes best), then by first mention
        picked.append((-len(set(hits)), pos, {"uri": cap.uri, "payload": payload}))
    return [step for _, _, step in sorted(picked, key=lambda x: (x[0], x[1]))]


def run_goal(goal: str, *, node: str = NODE, undo: bool = True) -> dict:
    reg = twin_registry(node)
    steps = plan_flow_nl(reg, goal)
    ev = Events()
    ev.emit("nl://goal/command/plan", actor="operator", goal=goal, steps=[s["uri"] for s in steps])
    result = run_flow(reg, steps, events=ev)

    undone = []
    if undo and result.get("ok"):
        # auto-rollback reversible steps, newest first, using the node's concrete inverse
        for i in range(len(result["results"]) - 1, -1, -1):
            step_result = result["results"][i]
            u = plan_undo(reg, step_result)
            if u:
                dispatch(reg, u["uri"], u["payload"], events=ev, actor="operator")
                undone.append(u["uri"])
    ev.emit("nl://goal/command/done", actor="operator", ran=len(steps), undone=len(undone))
    _emit_metric(goal, [s["uri"] for s in steps], bool(result.get("ok")), undone)
    return {"goal": goal, "steps": [s["uri"] for s in steps],
            "ok": result.get("ok"), "undone": undone, "events": ev.log,
            "results": result.get("results", [])}


def _emit_metric(goal, steps, ok, undone):
    import json
    body = json.dumps({"uri": "metric://nl/goal/query/summary", "actor": "twin-nl",
                       "payload": {"goal": goal, "planned_steps": steps, "ran_ok": ok,
                                   "auto_rolled_back": undone, "deterministic": True,
                                   "needs_llm": False, "on_live_node": True}}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            os.environ.get("EVENTBUS_URL", "http://127.0.0.1:28800") + "/emit",
            data=body, headers={"Content-Type": "application/json"}), timeout=3).read()
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    goal = " ".join(sys.argv[1:]) or "otwórz terminal i zrób zrzut ekranu na pc1"
    r = run_goal(goal)
    print("Cel:", r["goal"])
    print("Zaplanowana sekwencja:")
    for s in r["steps"]:
        print("  →", s)
    print("Wykonano:", r["ok"], "| auto-cofnięto:", r["undone"])
