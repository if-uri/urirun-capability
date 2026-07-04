"""NL office goal -> composed flow -> REAL execution on the live twin.

Unlike office_nl.py (in-process handlers), here the composed flow runs on the
live pc1 node: an office worker's goal opens the company shop in the desktop
browser and captures the confirmation — the same loop as episode 07, but driven
end to end through the mesh from a Polish goal, no LLM.

Gated by a running twin (pc1 node on :28765, shop on netpl).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from capability import Capability, Registry, Events, dispatch
from twin_nl import plan_flow_nl

NODE = os.environ.get("PC1_NODE", "http://127.0.0.1:28765")
SHOP = os.environ.get("SHOP_URL", "http://shop:9850")
SHOTS = Path(__file__).resolve().parents[1] / "pc1" / "reports" / "screenshots"


def office_twin_registry(node: str = NODE) -> Registry:
    reg = Registry()
    reg.add(Capability(
        uri="app://pc1/desktop/command/launch", effect="command", reversible=True,
        input={"type": "object", "required": ["app"], "properties": {"app": {"type": "string"}}},
        output={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        examples=({"input": {"app": "chromium",
                             "args": ["--no-sandbox", f"--app={SHOP}", "--force-device-scale-factor=1.2"],
                             "settle": 6},
                   "output": {"ok": True}},),
        adapter="http-node",
        config={"node": node, "remoteUri": "app://host/desktop/command/launch",
                "keywords": "sklep otworz otwórz zamow zamów zamówienie kup cybermysz mysz sprzet"}))
    reg.add(Capability(
        uri="kvm://pc1/screen/query/capture", effect="query",
        input={"type": "object", "properties": {"base64": {"type": "boolean"}}},
        output={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
        examples=({"input": {"base64": True}, "output": {"ok": True}},),
        adapter="http-node",
        config={"node": node, "remoteUri": "kvm://host/screen/query/capture",
                "keywords": "zrzut ekran ekranu screenshot potwierdzenie zdjecie zdjęcie"}))
    return reg


def run_office_goal_on_twin(goal: str, *, node: str = NODE, shot_name: str = "40-office-nl-shop") -> dict:
    reg = office_twin_registry(node)
    steps = plan_flow_nl(reg, goal)
    ev = Events()
    ev.emit("nl://office-twin/command/plan", actor="pracownik", goal=goal,
            steps=[s["uri"] for s in steps])
    saved = None
    all_ok = True
    for step in steps:
        out = dispatch(reg, step["uri"], step["payload"], events=ev, actor="pracownik")
        all_ok = all_ok and out.get("ok", False)
        if out.get("ok") and step["uri"].endswith("/screen/query/capture"):
            b64 = (out["result"] or {}).get("pngBase64")
            if b64:
                SHOTS.mkdir(parents=True, exist_ok=True)
                saved = SHOTS / f"{shot_name}.png"
                saved.write_bytes(base64.b64decode(b64))
    ev.emit("nl://office-twin/command/done", actor="pracownik", ran=len(steps),
            ok=all_ok, shot=str(saved) if saved else None)
    return {"goal": goal, "steps": [s["uri"] for s in steps], "ok": all_ok,
            "shot": str(saved) if saved else None, "events": ev.log}


if __name__ == "__main__":
    import sys, time  # noqa: E401
    goal = " ".join(sys.argv[1:]) or "otwórz sklep CyberMysz na pc1 i zrób zrzut zamówienia"
    r = run_office_goal_on_twin(goal)
    print("Cel:", r["goal"])
    print("Sekwencja wykonana na żywym pc1:")
    for s in r["steps"]:
        print("  →", s)
    print("Zrzut:", r["shot"])
